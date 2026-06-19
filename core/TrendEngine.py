def detect_trend(avg_bias: float, avg_strength: float) -> dict:
    abs_bias = abs(avg_bias)

    # Suppressed or unclear
    if abs_bias < 1.5 or avg_strength < 4:
        return {
            "trend": "Unclear",
            "reason": f"Bias {round(avg_bias, 1)} or strength {round(avg_strength, 1)} below threshold"
        }

    # Strong directional bias
    if avg_bias >= 2.5:
        return {
            "trend": "Up",
            "reason": f"Bias {round(avg_bias, 1)} strongly bullish"
        }
    elif avg_bias <= -2.5:
        return {
            "trend": "Down",
            "reason": f"Bias {round(avg_bias, 1)} strongly bearish"
        }

    # Borderline bias
    if 1.5 <= avg_bias < 2.5:
        return {
            "trend": "Up (soft)",
            "reason": f"Bias {round(avg_bias, 1)} mildly bullish"
        }
    elif -2.5 < avg_bias <= -1.5:
        return {
            "trend": "Down (soft)",
            "reason": f"Bias {round(avg_bias, 1)} mildly bearish"
        }

    # Neutral zone
    return {
        "trend": "Sideways",
        "reason": f"Bias {round(avg_bias, 1)} within neutral zone"
    }
