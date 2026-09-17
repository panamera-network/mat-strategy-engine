from datetime import datetime, timezone
from typing import List, Optional

from core.BalanceRangeEngine import detect_balance_range
from core.CandleEngine import CandleEngine
from core.demand_engine import DemandEngine, compute_atr, derive_freshness_state, derive_structural_evidence, link_zone_to_leg_origin
from core.FVGEngine import detect_fvg
from core.MomentumEngine import MomentumEngine
from core.OrderBlockEngine import detect_order_blocks
from core.StrengthEngine import StrengthEngine
from core.core_models import PriceSnapshot, StructureSnapshot
from core.structure_utils import (
    SWING_LOOKBACK,
    SWING_WINDOW,
    detect_breakout_retest,
    detect_choch_then_bos,
    detect_inside_bar_sequence,
    detect_snr_role_flip,
    detect_structure_event,
    detect_three_inside_sequence,
    detect_three_soldiers_crows_sequence,
    detect_trend,
    derive_snr_levels,
    find_swings,
    label_recent_candles,
    label_swing_points,
)
from core.VolumeProfileEngine import build_volume_profile

candle_engine = CandleEngine()
momentum_engine = MomentumEngine(candle_engine)
strength_engine = StrengthEngine()

FETCH_COUNT = SWING_LOOKBACK + SWING_WINDOW * 2  # buffer so the lookback window is fully confirmable


# ─────────────────────────────────────────────
# 🧠 Structure Engine
class StructureEngine:
    def __init__(self, candle_engine: CandleEngine, demand_engine: Optional[DemandEngine] = None):
        self.candle_engine = candle_engine
        # Optional — injected by the composition root (api/core_router.py).
        # context_zone/context_level now come exclusively from DemandEngine's
        # canonical get_context() (Fix #4C). The old 2-candle detect_snd()
        # heuristic this used to call has since been removed entirely
        # (Fix #4E1). If no demand_engine is injected, context degrades to
        # ("neutral", None) rather than detecting independently.
        self.demand_engine = demand_engine

    def get_snapshot(self, symbol: str, tf: str, cache=None, zones=None) -> Optional[StructureSnapshot]:
        candles = self.candle_engine.get_snapshots(symbol, tf, count=FETCH_COUNT, cache=cache)
        if len(candles) < SWING_WINDOW * 2 + 1:
            return None

        lookback = candles[-SWING_LOOKBACK:] if len(candles) > SWING_LOOKBACK else candles
        swing_highs, swing_lows = find_swings(lookback)
        structure_event = detect_structure_event(lookback, swing_highs, swing_lows)
        # Fix #7P — reuses the SAME already-fetched `lookback` window and
        # the SAME already-decided structure_event (no duplicate BOS/CHoCH
        # classification); only scans for the break's true origin candle
        # and any later retest. See detect_breakout_retest()'s own
        # docstring for the full audit rationale (v1 BOS-only).
        breakout_retest = detect_breakout_retest(lookback, structure_event)
        # Fix #7T -- reuses the SAME already-fetched `lookback` window and
        # the SAME already-decided structure_event (no duplicate BOS/CHoCH
        # classification); replays find_swings()/detect_structure_event()
        # on shorter prefixes of this same window to recover genuine
        # prior-CHoCH-before-this-BOS sequence evidence. See
        # detect_choch_then_bos()'s own docstring for the full audit
        # rationale.
        choch_then_bos = detect_choch_then_bos(lookback, structure_event)
        swing_points = label_swing_points(lookback, swing_highs, swing_lows)
        snr_levels = derive_snr_levels(lookback, swing_highs, swing_lows, structure_event)
        # Fix #7W — reuses the SAME already-fetched `lookback` window and
        # the SAME already-derived `snr_levels` list (no new fetch, no new
        # S&R detection, not coupled to structure_event/BOS/CHoCH); scans
        # for a genuine breakout-then-later-retest role flip on any
        # Resistance/Support level. See detect_snr_role_flip()'s own
        # docstring for the full audit rationale.
        snr_role_flip = detect_snr_role_flip(lookback, snr_levels)
        order_blocks = detect_order_blocks(lookback, [structure_event], timeframe=tf)
        fvg = detect_fvg(lookback, timeframe=tf)
        # Fix #7K -- reuses the same already-fetched `candles` window (no
        # new fetch); last 3 by default, enough for a 3-candle sequence
        # strategy.
        recent_candles = label_recent_candles(candles, count=3)

        # Fix #2 — event index/timestamp evidence, derived independently
        # here so this evidence works standalone. None when there's no
        # valid event, same as broken_level.
        event_index = structure_event.get("index") if structure_event.get("valid") else None
        event_timestamp = (
            str(lookback[event_index].timestamp)
            if isinstance(event_index, int) and 0 <= event_index < len(lookback)
            else None
        )

        prev, curr = candles[-2], candles[-1]
        price = PriceSnapshot(
            symbol=symbol,
            timeframe=tf,
            high=curr.high,
            low=curr.low,
            prev_high=prev.high,
            prev_low=prev.low
        )

        # Fix #4C — canonical context_zone/context_level, via DemandEngine's
        # get_context() (same call, same cache, no separate computation of
        # our own). The old detect_snd() heuristic this replaced has been
        # removed entirely (Fix #4E1), not just unused.
        # Fix #4D3 — optional `zones` (a caller-precomputed zone list, e.g.
        # Output.py's request-scoped zones_map[tf]) is passed straight
        # through so get_context() can skip its own detect_zones() call.
        # None (every caller besides Output.py) behaves exactly as before.
        if self.demand_engine is not None:
            context_zone, context_level = self.demand_engine.get_context(symbol, tf, cache=cache, zones=zones)
        else:
            context_zone, context_level = "neutral", None

        # Fix #5G1 — deterministic zone <-> leg origin link, reusing the
        # same `zones` list already available here (no new detect_zones()
        # call). See link_zone_to_leg_origin() for the matching rule; None
        # when there's no confirmed event or no zone satisfies it.
        origin_zone = link_zone_to_leg_origin(
            zones if zones is not None else [],
            structure_valid=structure_event.get("valid", False),
            structure_direction=structure_event.get("direction", "Neutral"),
            leg_origin_timestamp=structure_event.get("leg_origin_timestamp"),
            leg_origin_price=structure_event.get("leg_origin_price"),
            event_timestamp=event_timestamp,
            timeframe=tf,
        )

        # Fix #7M — the same canonical active-zone selection get_context()
        # above already uses (demand_engine.get_active_zone(), reusing the
        # same `zones`/candles -- no second fetch), but keeping the zone
        # object itself so its own freshness/structural evidence can be
        # exposed. derive_freshness_state()/derive_structural_evidence()
        # (Fix #5H2) are the same existing canonical reasoning Output.py's
        # _build_supply_demand_zones() already applies -- no new touch/
        # mitigation logic, no new formula. None when there is no active
        # zone for this symbol/timeframe, and also None (degrades
        # gracefully, same philosophy as no demand_engine at all -> the
        # context_zone/context_level "neutral" degrade above) for any
        # injected demand_engine that predates this method -- e.g.
        # tests/test_structure_engine_context.py's FakeDemandEngine, which
        # only implements get_context() and must keep working unchanged.
        active_zone = None
        if self.demand_engine is not None:
            get_active_zone_method = getattr(self.demand_engine, "get_active_zone", None)
            if get_active_zone_method is not None:
                active_zone = get_active_zone_method(symbol, tf, cache=cache, zones=zones)
        active_zone_freshness = derive_freshness_state(active_zone) if active_zone else None
        active_zone_structural_evidence = (
            derive_structural_evidence(
                active_zone,
                origin_zone.type if origin_zone else None,
                origin_zone.timestamp if origin_zone else None,
                origin_zone.top if origin_zone else None,
                origin_zone.bottom if origin_zone else None,
            )
            if active_zone else None
        )

        # Fix #7N — a SEPARATE selector from active_zone above:
        # get_nearest_mitigated_zone() is a sibling to get_active_zone(),
        # neither of which is modified here. Same defensive getattr
        # pattern as active_zone (degrades to None for any demand_engine
        # stub that predates this method), same already-fetched
        # `zones`/candles (no new fetch, no new mitigation calculation).
        mitigated_zone = None
        if self.demand_engine is not None:
            get_mitigated_zone_method = getattr(self.demand_engine, "get_nearest_mitigated_zone", None)
            if get_mitigated_zone_method is not None:
                mitigated_zone = get_mitigated_zone_method(symbol, tf, cache=cache, zones=zones)
        mitigated_zone_structural_evidence = (
            derive_structural_evidence(
                mitigated_zone,
                origin_zone.type if origin_zone else None,
                origin_zone.timestamp if origin_zone else None,
                origin_zone.top if origin_zone else None,
                origin_zone.bottom if origin_zone else None,
            )
            if mitigated_zone else None
        )

        snapshot = StructureSnapshot(
            symbol=symbol,
            timeframe=tf,
            current_high=price.high,
            current_low=price.low,
            prev_high=price.prev_high,
            prev_low=price.prev_low,
            current_zone="Neutral",
            prev_zone="Neutral",
            momentum=0.0,
            timestamp=datetime.now(timezone.utc),
            context_zone=context_zone,
            context_level=context_level,
            snr_levels=snr_levels,
            order_blocks=order_blocks,
            fvg=fvg,
            recent_candles=recent_candles,
            swing_points=swing_points,
            event_broken_level=structure_event.get("broken_level"),
            event_index=event_index,
            event_timestamp=event_timestamp,
            # Fix #5F2 — structural leg origin evidence. detect_structure_event()
            # already guarantees these are None exactly when there's no
            # confirmed event, same as broken_level — no extra guard needed here.
            leg_origin_index=structure_event.get("leg_origin_index"),
            leg_origin_timestamp=structure_event.get("leg_origin_timestamp"),
            leg_origin_price=structure_event.get("leg_origin_price"),
            leg_origin_swing_label=structure_event.get("leg_origin_swing_label"),
            # Fix #5G1 — minimal evidence only, never the whole zone object.
            origin_zone_type=origin_zone.type if origin_zone else None,
            origin_zone_timestamp=origin_zone.timestamp if origin_zone else None,
            origin_zone_top=origin_zone.top if origin_zone else None,
            origin_zone_bottom=origin_zone.bottom if origin_zone else None,
            # Fix #6C — pre-break trend evidence. detect_structure_event()
            # already guarantees this is None exactly when there's no
            # confirmed event, same as broken_level/leg_origin_* above.
            pre_break_trend=structure_event.get("pre_break_trend"),
            # Fix #7M — canonical active-zone evidence, computed above.
            active_zone_type=active_zone.type if active_zone else None,
            active_zone_top=active_zone.top if active_zone else None,
            active_zone_bottom=active_zone.bottom if active_zone else None,
            active_zone_freshness=active_zone_freshness,
            active_zone_structural_evidence=active_zone_structural_evidence,
            active_zone_timestamp=active_zone.timestamp if active_zone else None,
            # getattr, not direct access: candle_index is ambient-WIP-only
            # on SupplyDemandZone (committed HEAD deliberately left it out,
            # per Fix #5B -- "still WIP-only, not needed for
            # reversal/continuation/unknown"); this degrades to None on a
            # committed-only SupplyDemandZone rather than crashing.
            active_zone_index=getattr(active_zone, "candle_index", None) if active_zone else None,
            # Fix #7N — straight copy from the canonical zone's own
            # touch_count (Fix #5E3, already committed), no new counting.
            active_zone_touch_count=active_zone.touch_count if active_zone else None,
            # Fix #7N — SEPARATE mitigated-zone evidence bundle, computed
            # above via the sibling get_nearest_mitigated_zone() selector.
            mitigated_zone_type=mitigated_zone.type if mitigated_zone else None,
            mitigated_zone_top=mitigated_zone.top if mitigated_zone else None,
            mitigated_zone_bottom=mitigated_zone.bottom if mitigated_zone else None,
            mitigated_zone_structural_evidence=mitigated_zone_structural_evidence,
            mitigated_zone_timestamp=mitigated_zone.timestamp if mitigated_zone else None,
            # getattr, not direct access: candle_index is ambient-WIP-only
            # on SupplyDemandZone, same caveat as active_zone_index above.
            mitigated_zone_index=getattr(mitigated_zone, "candle_index", None) if mitigated_zone else None,
            mitigated_zone_touch_count=mitigated_zone.touch_count if mitigated_zone else None,
            # Fix #7P — genuine breakout-then-later-retest evidence,
            # computed above via detect_breakout_retest() (no duplicate
            # BOS/CHoCH calculation, reuses the already-decided
            # structure_event and the already-fetched lookback window).
            breakout_origin_index=breakout_retest["breakout_origin_index"],
            breakout_origin_timestamp=breakout_retest["breakout_origin_timestamp"],
            retest_index=breakout_retest["retest_index"],
            retest_timestamp=breakout_retest["retest_timestamp"],
            retest_confirmed=breakout_retest["retest_confirmed"],
            # Fix #7T -- genuine prior-CHoCH-before-this-BOS sequence
            # evidence, computed above via detect_choch_then_bos() (no
            # duplicate BOS/CHoCH calculation, reuses the already-decided
            # structure_event and the already-fetched lookback window).
            choch_confirmed=choch_then_bos["choch_confirmed"],
            choch_index=choch_then_bos["choch_index"],
            choch_timestamp=choch_then_bos["choch_timestamp"],
            choch_broken_level=choch_then_bos["choch_broken_level"],
            # Fix #7T (BOS origin identity audit) -- the true origin of the
            # CURRENT BOS leg (Fix #7P's own current-leg backward-origin
            # principle, reused via the same _find_current_leg_origin()
            # helper detect_breakout_retest() now also uses) -- NOT
            # event_index/event_timestamp above, which always describe
            # "now" and can be several candles later than where this BOS
            # leg actually began.
            bos_origin_index=choch_then_bos["bos_origin_index"],
            bos_origin_timestamp=choch_then_bos["bos_origin_timestamp"],
            # Fix #7V -- straight copy of the same current candle (curr,
            # already in scope above) current_high/current_low already
            # use. No new fetch, no recomputation.
            current_close=curr.close,
            # Fix #7W — genuine S&R role-flip evidence, computed above via
            # detect_snr_role_flip() (no duplicate S&R detection, reuses
            # the already-derived snr_levels list and the already-fetched
            # lookback window).
            snr_flip_confirmed=snr_role_flip["confirmed"],
            snr_flip_direction=snr_role_flip["direction"],
            snr_flip_original_role=snr_role_flip["original_role"],
            snr_flip_new_role=snr_role_flip["new_role"],
            snr_flip_level=snr_role_flip["level"],
            snr_flip_breakout_index=snr_role_flip["breakout_index"],
            snr_flip_breakout_timestamp=snr_role_flip["breakout_timestamp"],
            snr_flip_retest_index=snr_role_flip["retest_index"],
            snr_flip_retest_timestamp=snr_role_flip["retest_timestamp"],
        )

        snapshot.structure_type = structure_event["type"]
        snapshot.structure_direction = structure_event["direction"]
        snapshot.structure_valid = structure_event["valid"]

        momentum_snapshot = momentum_engine.compute(candles, symbol, tf)
        snapshot.momentum = momentum_snapshot.momentum
        snapshot.confidence_drop = momentum_snapshot.confidence_drop
        # Fix #6V — canonical signed, dimensionless momentum (slope2/ATR14).
        # `candles` here is already the full FETCH_COUNT (26) window, well
        # above ATR14_MIN_CANDLES, so this is populated from the same
        # compute() call above — no extra fetch, no second MomentumEngine
        # call.
        snapshot.atr_normalized_momentum = momentum_snapshot.atr_normalized_momentum

        # Fix #7U -- genuine expansion -> pullback -> recovery momentum
        # sequence evidence, reusing the SAME already-fetched `candles`
        # window and the SAME momentum_engine already used for the current
        # atr_normalized_momentum reading above -- no new fetch, no second
        # momentum formula. See MomentumEngine.detect_pullback_recovery()'s
        # own docstring for the full audit rationale.
        pullback_recovery = momentum_engine.detect_pullback_recovery(candles, symbol, tf)
        snapshot.momentum_sequence_confirmed = pullback_recovery["confirmed"]
        snapshot.momentum_sequence_direction = pullback_recovery["direction"]
        snapshot.momentum_expansion_index = pullback_recovery["expansion_index"]
        snapshot.momentum_expansion_timestamp = pullback_recovery["expansion_timestamp"]
        snapshot.momentum_expansion_value = pullback_recovery["expansion_momentum"]
        snapshot.momentum_pullback_index = pullback_recovery["pullback_index"]
        snapshot.momentum_pullback_timestamp = pullback_recovery["pullback_timestamp"]
        snapshot.momentum_pullback_value = pullback_recovery["pullback_momentum"]
        snapshot.momentum_recovery_index = pullback_recovery["recovery_index"]
        snapshot.momentum_recovery_timestamp = pullback_recovery["recovery_timestamp"]
        snapshot.momentum_recovery_value = pullback_recovery["recovery_momentum"]

        # Fix #7Y — Balance Range evidence (canonical, neutral naming --
        # see core.BalanceRangeEngine's own module docstring for the
        # rename rationale), detected on THIS SAME (symbol, tf)'s
        # already-fetched `candles` window (no new fetch -- see
        # core.BalanceRangeEngine's own module docstring for the
        # timeframe-choice audit and rationale). compute_atr() is the
        # SAME canonical ATR(14) helper core.demand_engine already uses
        # for zone detection -- no second formula. Feeds the detected
        # range directly into Fix #7X's own unchanged build_volume_
        # profile() -- no second VP implementation.
        #
        # Fix #7Y (temporal-integrity audit, before this fix's first
        # commit) — detection and the profile it feeds are built from
        # `candles[:-1]` (everything up to and including candle N-1),
        # deliberately EXCLUDING the current candle (N) that a Strategy
        # will react to. A live audit found including candle N could
        # shift VAH by real amounts (a candle with unusually large
        # tick_volume measurably moved the value-area boundary) and, more
        # seriously, could make detection fail ENTIRELY for the exact
        # geometry a VAH/VAL reaction is supposed to catch: a genuine
        # rejection candle wicks slightly beyond the old range before
        # closing back inside, and using it to SEED the backward
        # expansion (the old design) could blow the compression bound and
        # report "no range" instead of a valid reaction. The level a
        # Strategy reacts to must already exist before the reaction
        # candle is evaluated -- ATR, range detection, and the profile
        # are now frozen as of N-1; only the Strategy's own eligibility
        # check (current_high/current_low/current_close, already sourced
        # from candle N elsewhere on this snapshot) ever looks at N.
        historical_candles = candles[:-1]
        balance_atr = compute_atr(historical_candles)
        balance_range = detect_balance_range(historical_candles, balance_atr)
        snapshot.balance_range_confirmed = balance_range["confirmed"]
        snapshot.balance_range_start_index = balance_range["start_index"]
        snapshot.balance_range_start_timestamp = balance_range["start_timestamp"]
        snapshot.balance_range_end_index = balance_range["end_index"]
        snapshot.balance_range_end_timestamp = balance_range["end_timestamp"]
        snapshot.balance_range_high = balance_range["range_high"]
        snapshot.balance_range_low = balance_range["range_low"]
        if balance_range["confirmed"]:
            range_candles = historical_candles[balance_range["start_index"]:balance_range["end_index"] + 1]
            balance_profile = build_volume_profile(range_candles, symbol=symbol, timeframe=tf)
            if balance_profile is not None:
                snapshot.balance_range_poc = balance_profile.poc_price
                snapshot.balance_range_vah = balance_profile.value_area_high
                snapshot.balance_range_val = balance_profile.value_area_low
                snapshot.balance_range_total_volume = balance_profile.total_volume
                snapshot.balance_range_value_area_pct = balance_profile.value_area_pct
                snapshot.balance_range_num_bins = balance_profile.num_bins
                snapshot.balance_range_source_type = balance_profile.source_type

        # Fix #7AA — MAT Inside Bar sequence evidence (Mother Bar -> >=3
        # contained children -> body breakout), detected on THIS SAME
        # already-fetched `candles` window (no new fetch -- see
        # structure_utils.detect_inside_bar_sequence()'s own docstring
        # for the full evidence audit, equality-semantics decision, and
        # stale-Mother selection rule).
        inside_bar = detect_inside_bar_sequence(candles)
        snapshot.inside_bar_confirmed = inside_bar["confirmed"]
        snapshot.inside_bar_direction = inside_bar["direction"]
        snapshot.inside_bar_mother_index = inside_bar["mother_index"]
        snapshot.inside_bar_mother_timestamp = inside_bar["mother_timestamp"]
        snapshot.inside_bar_mother_open = inside_bar["mother_open"]
        snapshot.inside_bar_mother_high = inside_bar["mother_high"]
        snapshot.inside_bar_mother_low = inside_bar["mother_low"]
        snapshot.inside_bar_mother_close = inside_bar["mother_close"]
        snapshot.inside_bar_children_count = inside_bar["children_count"]
        snapshot.inside_bar_children_start_index = inside_bar["children_start_index"]
        snapshot.inside_bar_children_start_timestamp = inside_bar["children_start_timestamp"]
        snapshot.inside_bar_children_end_index = inside_bar["children_end_index"]
        snapshot.inside_bar_children_end_timestamp = inside_bar["children_end_timestamp"]
        snapshot.inside_bar_breakout_index = inside_bar["breakout_index"]
        snapshot.inside_bar_breakout_timestamp = inside_bar["breakout_timestamp"]
        snapshot.inside_bar_breakout_close = inside_bar["breakout_close"]

        # Fix #7AB — MAT Three Inside Up/Down sequence evidence (fixed
        # exactly-3-candle pattern: C1 -> C2 body-in-body containment ->
        # C3 confirmation), detected on THIS SAME already-fetched
        # `candles` window (no new fetch -- see structure_utils.detect_
        # three_inside_sequence()'s own docstring for the full audit and
        # locked-rule detail).
        three_inside = detect_three_inside_sequence(candles)
        snapshot.three_inside_confirmed = three_inside["confirmed"]
        snapshot.three_inside_direction = three_inside["direction"]
        snapshot.three_inside_c1_index = three_inside["c1_index"]
        snapshot.three_inside_c1_timestamp = three_inside["c1_timestamp"]
        snapshot.three_inside_c1_open = three_inside["c1_open"]
        snapshot.three_inside_c1_high = three_inside["c1_high"]
        snapshot.three_inside_c1_low = three_inside["c1_low"]
        snapshot.three_inside_c1_close = three_inside["c1_close"]
        snapshot.three_inside_c2_index = three_inside["c2_index"]
        snapshot.three_inside_c2_timestamp = three_inside["c2_timestamp"]
        snapshot.three_inside_c2_open = three_inside["c2_open"]
        snapshot.three_inside_c2_high = three_inside["c2_high"]
        snapshot.three_inside_c2_low = three_inside["c2_low"]
        snapshot.three_inside_c2_close = three_inside["c2_close"]
        snapshot.three_inside_c3_index = three_inside["c3_index"]
        snapshot.three_inside_c3_timestamp = three_inside["c3_timestamp"]
        snapshot.three_inside_c3_open = three_inside["c3_open"]
        snapshot.three_inside_c3_high = three_inside["c3_high"]
        snapshot.three_inside_c3_low = three_inside["c3_low"]
        snapshot.three_inside_c3_close = three_inside["c3_close"]

        # Fix #7AC — MAT Three White Soldiers / Three Black Crows
        # sequence evidence (fixed exactly-3-candle pattern: three
        # same-color candles with progressively-extending closes, each
        # opening inside the prior candle's real body), detected on THIS
        # SAME already-fetched `candles` window (no new fetch -- see
        # structure_utils.detect_three_soldiers_crows_sequence()'s own
        # docstring for the full audit and locked-rule detail).
        three_soldiers_crows = detect_three_soldiers_crows_sequence(candles)
        snapshot.three_soldiers_crows_confirmed = three_soldiers_crows["confirmed"]
        snapshot.three_soldiers_crows_direction = three_soldiers_crows["direction"]
        snapshot.three_soldiers_crows_c1_index = three_soldiers_crows["c1_index"]
        snapshot.three_soldiers_crows_c1_timestamp = three_soldiers_crows["c1_timestamp"]
        snapshot.three_soldiers_crows_c1_open = three_soldiers_crows["c1_open"]
        snapshot.three_soldiers_crows_c1_high = three_soldiers_crows["c1_high"]
        snapshot.three_soldiers_crows_c1_low = three_soldiers_crows["c1_low"]
        snapshot.three_soldiers_crows_c1_close = three_soldiers_crows["c1_close"]
        snapshot.three_soldiers_crows_c2_index = three_soldiers_crows["c2_index"]
        snapshot.three_soldiers_crows_c2_timestamp = three_soldiers_crows["c2_timestamp"]
        snapshot.three_soldiers_crows_c2_open = three_soldiers_crows["c2_open"]
        snapshot.three_soldiers_crows_c2_high = three_soldiers_crows["c2_high"]
        snapshot.three_soldiers_crows_c2_low = three_soldiers_crows["c2_low"]
        snapshot.three_soldiers_crows_c2_close = three_soldiers_crows["c2_close"]
        snapshot.three_soldiers_crows_c3_index = three_soldiers_crows["c3_index"]
        snapshot.three_soldiers_crows_c3_timestamp = three_soldiers_crows["c3_timestamp"]
        snapshot.three_soldiers_crows_c3_open = three_soldiers_crows["c3_open"]
        snapshot.three_soldiers_crows_c3_high = three_soldiers_crows["c3_high"]
        snapshot.three_soldiers_crows_c3_low = three_soldiers_crows["c3_low"]
        snapshot.three_soldiers_crows_c3_close = three_soldiers_crows["c3_close"]

        strength_diag = strength_engine.compute_strength(candles)
        snapshot.strength = strength_diag.strength
        snapshot.body_ratio = strength_diag.avg_body_ratio
        snapshot.momentum_slope = strength_diag.momentum_slope

        # Fix #6AO — legacy detect_suppression() gate retired from the live
        # path. Fix #6AN's audit found: 83-94% suppression rate (live and
        # rolling-historical), 96-99% of it from the single condition
        # (strength < 4) Fix #6P/#6Q already found does not discriminate
        # good setups from bad; no evidence the blocked candidates were
        # systematically worse (Fix #6AN Q4/Q5, reinforced by Fix #6AM's
        # finding that extreme ATR momentum correlates with MORE valid
        # structural events, not fewer); no hidden safety/execution
        # consumer depends on it (Fix #6AN Q6 -- this repo has no
        # execution layer at all). suppression/suppression_reason are
        # preserved as always-inactive fields for API/backward
        # compatibility -- SuppressionEngine.py, its detect_suppression()
        # function, and its orphaned helper functions are untouched; this
        # is the one live call site that stops invoking the gate. No
        # replacement threshold, body_dominance/conviction/ATR-extreme/
        # pre_break_trend gate, or any other new condition is introduced.
        snapshot.suppression_reason = ""
        snapshot.suppression = False

        structure_map = {
            "BOS": "breakout",
            "CHOCH": "reversal",
        }
        snapshot.structure = structure_map.get(snapshot.structure_type, "neutral")

        return snapshot

    def batch_snapshots(self, symbols: List[str], tf: str, cache=None) -> List[StructureSnapshot]:
        results = []
        for symbol in symbols:
            snapshot = self.get_snapshot(symbol, tf, cache=cache)
            if snapshot and snapshot.structure_valid:
                results.append(snapshot)
        return results
