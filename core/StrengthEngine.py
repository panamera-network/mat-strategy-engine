from core.core_models import CandleSnapshot, StrengthDiagnostic


class StrengthEngine:
    def compute_strength(self, candles: list[CandleSnapshot]) -> StrengthDiagnostic:
        if not candles:
            return StrengthDiagnostic(0.0, 0.0, 0.0)

        body_ratios = [c.body / c.range if c.range > 0 else 0.0 for c in candles]
        avg_body_ratio = sum(body_ratios) / len(body_ratios)

        closes = [c.close for c in candles[-5:]]
        momentum_slope = closes[-1] - closes[0] if len(closes) == 5 else 0.0

        raw_strength = avg_body_ratio * 5 + (momentum_slope / candles[-1].range if candles[-1].range else 0)
        strength = round(min(max(raw_strength, 0.0), 10.0), 2)

        
        return StrengthDiagnostic(strength, avg_body_ratio, momentum_slope)

def is_bias_weak(strength: float, threshold: float = 4.0) -> tuple[bool, str]:
    if strength < threshold:
        return True, f"Bias strength {strength} is below threshold {threshold}"
    return False, ""