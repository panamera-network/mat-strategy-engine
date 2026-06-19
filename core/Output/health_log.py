import logging

from core.Output.helper import BIAS_ORDER, SCALPING_ORDER, SWING_ORDER

def build_symbol_health(symbol: str, symbol_block: dict) -> dict:
    """Return a health summary dict and log it."""
    # --- Timeframe completeness ---
    bias_missing = [tf for tf in BIAS_ORDER if not symbol_block.get("bias", {}).get(tf)]
    scalping_missing = [tf for tf in SCALPING_ORDER if not symbol_block.get("scalping", {}).get(tf)]
    swing_missing = [tf for tf in SWING_ORDER if not symbol_block.get("swing", {}).get(tf)]

    health_summary = {
        "bias": {
            "present": len(BIAS_ORDER) - len(bias_missing),
            "total": len(BIAS_ORDER),
            "missing": bias_missing
        },
        "scalping": {
            "present": len(SCALPING_ORDER) - len(scalping_missing),
            "total": len(SCALPING_ORDER),
            "missing": scalping_missing
        },
        "swing": {
            "present": len(SWING_ORDER) - len(swing_missing),
            "total": len(SWING_ORDER),
            "missing": swing_missing
        }
    }

    # Log summary
    logging.info(
        f"[Health] {symbol}: "
        f"bias {health_summary['bias']['present']}/{health_summary['bias']['total']}, "
        f"scalping {health_summary['scalping']['present']}/{health_summary['scalping']['total']}, "
        f"swing {health_summary['swing']['present']}/{health_summary['swing']['total']}"
    )

    # Log missing TFs
    if bias_missing:
        logging.warning(f"[Health] {symbol} missing bias TFs: {', '.join(bias_missing)}")
    if scalping_missing:
        logging.warning(f"[Health] {symbol} missing scalping TFs: {', '.join(scalping_missing)}")
    if swing_missing:
        logging.warning(f"[Health] {symbol} missing swing TFs: {', '.join(swing_missing)}")

    # --- Metric completeness ---
    def check_metrics(mode_name, tf_list, required_fields):
        missing_metrics = {}
        for tf in tf_list:
            tf_data = symbol_block.get(mode_name, {}).get(tf)
            if not tf_data:
                continue
            missing_fields = [field for field in required_fields if tf_data.get(field) is None]
            if missing_fields:
                missing_metrics[tf] = missing_fields
                logging.warning(
                    f"[Health] {symbol} {mode_name} {tf} missing fields: {', '.join(missing_fields)}"
                )
        return missing_metrics

    health_summary["bias"]["missing_fields"] = check_metrics("bias", BIAS_ORDER, ["score", "strength"])
    health_summary["scalping"]["missing_fields"] = check_metrics("scalping", SCALPING_ORDER, ["momentum", "bias"])
    health_summary["swing"]["missing_fields"] = check_metrics("swing", SWING_ORDER, ["momentum", "bias"])

    return health_summary
