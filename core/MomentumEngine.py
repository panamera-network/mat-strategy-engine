from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot, MomentumSnapshot
from core.demand_engine import compute_atr

# Fix #6V — minimum candles for a genuine 14-period ATR (14 true-range
# values need 15 candles). Below this, atr_normalized_momentum is None
# rather than computed from a shorter/different-period ATR.
ATR14_MIN_CANDLES = 15

# Fix #7U — canonical momentum-history thresholds, reused from existing
# committed references rather than guessed:
#   EXPANSION_THRESHOLD (2.0) is Fix #7O's own audited
#   MomentumExpansionStrategy.MOMENTUM_THRESHOLD, reused verbatim as its
#   own named constant here (same pattern Fix #7O itself used when it
#   matched strategy_momentum_confidence()'s saturation cap rather than
#   importing across an unrelated module) -- not re-derived, not a second
#   independently-chosen number.
#   PULLBACK_WEAK_THRESHOLD (0.5) / RECOVERY_STRONG_THRESHOLD (1.0) reuse
#   core.Output.Output's own canonical momentum display bands
#   (ATR_MOMENTUM_MODERATE_THRESHOLD / ATR_MOMENTUM_STRONG_THRESHOLD,
#   Fix #6Z) -- "weak" (<0.5 ATR) is the existing canonical definition of
#   a momentum reading with no real conviction (a genuine pullback),
#   "strong" (>=1.0 ATR) is the existing canonical definition of a
#   momentum reading with real conviction (a genuine recovery). Not
#   imported directly (Output.py is a higher assembly layer that already
#   imports from core/ engines; importing the other way would invert that
#   dependency for two plain float constants) -- redefined here as its
#   own named copy of the same audited values, the same convention Fix
#   #7O's own threshold comment already established for this repo.
PULLBACK_WEAK_THRESHOLD = 0.5
RECOVERY_STRONG_THRESHOLD = 1.0
EXPANSION_THRESHOLD = 2.0


class MomentumEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine  # ✅ This line was missing

    def compute(self, candles: list[CandleSnapshot], symbol: str, timeframe: str) -> MomentumSnapshot:
        if len(candles) < 6:
            return MomentumSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                momentum=0.0,
                slope=0.0,
            )

        closes = [c.close for c in candles[-6:]]
        slope2 = closes[5] - closes[2]
        raw_score = slope2
        scaled_score = max(0.0, min(10.0, abs(raw_score) * 2.5))  # tweak scale_factor

        # Fix #6BD — confidence_drop retired: compatibility/deprecated
        # field, intentionally frozen to False. The old raw-price-unit
        # formula (slope2 < slope1 and abs(acceleration) > 0.5) is removed
        # -- Fix #6BC's audit found it severely instrument-scale-broken
        # (0% activation for FX, ~50% for crypto, purely from price scale)
        # with zero live behavioral consumer since Fix #6AO retired legacy
        # suppression. The field stays in MomentumSnapshot/StructureSnapshot/
        # BiasShiftEvent for /core/bias/shift* backward compatibility --
        # never backfilled with a new formula, threshold, or ATR-based
        # replacement.
        confidence_drop = False

        # Fix #6U/#6V — canonical signed, dimensionless momentum: the same
        # slope2 (3-bar displacement) above, divided by ATR14 — no clamp,
        # no multiplier, no threshold. Uses whatever `candles` this call
        # was already given (StructureEngine's canonical path already
        # passes its full 26-candle FETCH_COUNT window here — no extra
        # fetch). If this call was given fewer than ATR14_MIN_CANDLES
        # (e.g. MomentumEngine.get_momentum()'s own count=6 fetch),
        # atr_normalized_momentum is None — deliberately not backfilled
        # with a shorter/different-period ATR or any other fallback
        # denominator.
        atr_normalized_momentum = None
        if len(candles) >= ATR14_MIN_CANDLES:
            atr14 = compute_atr(candles, period=14)
            if atr14:
                atr_normalized_momentum = slope2 / atr14

        return MomentumSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            momentum=scaled_score,
            slope=round(slope2, 2),
            confidence_drop=confidence_drop,
            score=raw_score,
            atr_normalized_momentum=atr_normalized_momentum,
        )

    def get_momentum(self, symbol: str, timeframe: str, cache=None) -> MomentumSnapshot:
        candles = self.candle_engine.get_snapshots(symbol, timeframe, count=6, cache=cache)
        return self.compute(candles, symbol, timeframe)

    def detect_pullback_recovery(self, candles: list[CandleSnapshot], symbol: str, timeframe: str) -> dict:
        """Fix #7U — genuine expansion -> pullback -> recovery momentum
        sequence evidence, v1 baseline.

        Audit finding this method exists to fix: a single StructureSnapshot/
        StrategySnapshot only ever exposes atr_normalized_momentum "as of
        right now" -- it cannot by itself prove momentum was previously
        strong, then weakened, then recovered; there is no historical
        momentum series anywhere in committed code. Closes the gap by
        replaying self.compute() (the exact canonical slope2/ATR14 formula,
        never reimplemented or duplicated) on progressively shorter
        PREFIXES of the SAME already-fetched `candles` window StructureEngine
        already passes to compute() for the current reading -- no new
        fetch, no second momentum formula, no persistent state (a pure
        function of its own arguments, deterministic under repeated
        evaluation, and it carries no state of its own to leak across
        symbols or timeframes).

        v1 sequence (same direction throughout):
          1. expansion: an earlier candle where |atr_normalized_momentum|
             >= EXPANSION_THRESHOLD.
          2. pullback: a LATER candle where |atr_normalized_momentum| <
             PULLBACK_WEAK_THRESHOLD.
          3. recovery: the CURRENT (most recent) candle, where
             |atr_normalized_momentum| >= RECOVERY_STRONG_THRESHOLD and its
             sign matches the expansion's sign.

        Direction-flip-during-pullback decision (explicitly audited, not
        silently decided): the pullback test is on MAGNITUDE only
        (abs(momentum) < PULLBACK_WEAK_THRESHOLD), sign-agnostic -- at that
        low a magnitude, sign is noise, not a meaningful directional
        signal, so a momentary small sign flip on the pullback candle
        itself does not disqualify the sequence. A LARGE opposite-
        direction reading during either backward scan (abs(momentum) >=
        EXPANSION_THRESHOLD in the opposite sign) is different -- that is
        a genuine opposite expansion, not noise, and immediately
        invalidates the sequence being built rather than being silently
        allowed or silently absorbed into the pullback.

        Stale-sequence identity: scans strictly BACKWARD from "now", first
        for the NEAREST pullback candle, then from there for the NEAREST
        same-direction expansion candle before it -- the same "nearest
        first" principle Fix #7T proved for CHoCH-then-BOS sequence
        identity, so a stale, already-superseded expansion can never pair
        with an unrelated later recovery across an intervening opposite
        expansion: encountering an opposite-direction candle at or above
        EXPANSION_THRESHOLD at any point during either backward scan
        immediately rejects the sequence (no_evidence) rather than
        continuing past it.

        v1 scope: only a sequence within this same bounded already-fetched
        window is ever found (no sequence expiry / max-bars-between-stages
        rule yet, deferred to a later rule audit); a moderate opposite-
        direction reading (magnitude between the weak and expansion
        thresholds) neither satisfies pullback nor triggers the stale-
        rejection -- scanning simply continues past it, an explicitly
        deferred gray zone (opposite-direction excursion policy), not a
        resolved rule.

        Returns a dict with confirmed/direction/expansion_index/
        expansion_timestamp/expansion_momentum/pullback_index/
        pullback_timestamp/pullback_momentum/recovery_index/
        recovery_timestamp/recovery_momentum -- all False/None whenever
        the current reading is missing/not genuinely recovered, or no
        valid earlier pullback+expansion pair is found."""
        no_evidence = {
            "confirmed": False, "direction": None,
            "expansion_index": None, "expansion_timestamp": None, "expansion_momentum": None,
            "pullback_index": None, "pullback_timestamp": None, "pullback_momentum": None,
            "recovery_index": None, "recovery_timestamp": None, "recovery_momentum": None,
        }

        now_index = len(candles) - 1
        min_index = ATR14_MIN_CANDLES - 1
        if now_index < min_index:
            return no_evidence

        def momentum_at(i: int):
            return self.compute(candles[:i + 1], symbol, timeframe).atr_normalized_momentum

        recovery_momentum = momentum_at(now_index)
        if recovery_momentum is None or abs(recovery_momentum) < RECOVERY_STRONG_THRESHOLD:
            return no_evidence
        recovery_is_bullish = recovery_momentum > 0
        direction = "Bullish" if recovery_is_bullish else "Bearish"

        pullback_index = None
        pullback_momentum = None
        for i in range(now_index - 1, min_index - 1, -1):
            m = momentum_at(i)
            if m is None:
                continue
            if abs(m) >= EXPANSION_THRESHOLD and (m > 0) != recovery_is_bullish:
                return no_evidence
            if abs(m) < PULLBACK_WEAK_THRESHOLD:
                pullback_index = i
                pullback_momentum = m
                break
        if pullback_index is None:
            return no_evidence

        expansion_index = None
        expansion_momentum = None
        for i in range(pullback_index - 1, min_index - 1, -1):
            m = momentum_at(i)
            if m is None:
                continue
            if abs(m) >= EXPANSION_THRESHOLD:
                if (m > 0) == recovery_is_bullish:
                    expansion_index = i
                    expansion_momentum = m
                    break
                return no_evidence
        if expansion_index is None:
            return no_evidence

        return {
            "confirmed": True,
            "direction": direction,
            "expansion_index": expansion_index,
            "expansion_timestamp": str(candles[expansion_index].timestamp),
            "expansion_momentum": expansion_momentum,
            "pullback_index": pullback_index,
            "pullback_timestamp": str(candles[pullback_index].timestamp),
            "pullback_momentum": pullback_momentum,
            "recovery_index": now_index,
            "recovery_timestamp": str(candles[now_index].timestamp),
            "recovery_momentum": recovery_momentum,
        }

candle_engine = CandleEngine()
momentum_engine = MomentumEngine(candle_engine)
