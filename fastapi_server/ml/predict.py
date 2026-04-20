import joblib
import os
import pandas as pd
import numpy as np
from datetime import datetime

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

class PredictionEngine:
    def __init__(self):
        self.models = {}
        self.load_models()

    def load_models(self):
        try:
            self.models['temp_trend'] = joblib.load(os.path.join(MODEL_DIR, "temp_trend.pkl"))
            self.models['hum_trend'] = joblib.load(os.path.join(MODEL_DIR, "hum_trend.pkl"))
            self.models['watering'] = joblib.load(os.path.join(MODEL_DIR, "watering_model.pkl"))
            print("ML models loaded successfully")
        except Exception as e:
            print(f"Error loading models: {e}")

    @staticmethod
    def _pick_value(record, primary_key, fallback_key=None, default=0.0):
        value = record.get(primary_key)
        if value is None and fallback_key:
            value = record.get(fallback_key)
        if value is None:
            return float(default)
        return float(value)

    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))

    @staticmethod
    def _trend_label(delta, up_threshold, down_threshold):
        if delta > up_threshold:
            return "Rising"
        if delta < down_threshold:
            return "Falling"
        return "Stable"

    def _compute_dryness_risk(self, current_temp, current_hum, current_light, current_moisture, moisture_delta):
        # Weighted agronomy-inspired score from 0 to 100.
        moisture_component = self._clamp((40.0 - current_moisture) / 40.0, 0.0, 1.0) * 50.0
        heat_component = self._clamp((current_temp - 30.0) / 12.0, 0.0, 1.0) * 20.0
        dry_air_component = self._clamp((55.0 - current_hum) / 30.0, 0.0, 1.0) * 15.0
        light_component = self._clamp((current_light - 500.0) / 600.0, 0.0, 1.0) * 10.0
        decline_component = self._clamp((-moisture_delta) / 4.0, 0.0, 1.0) * 5.0
        return round(
            moisture_component
            + heat_component
            + dry_air_component
            + light_component
            + decline_component,
            1,
        )

    def _compute_watering_probability(self, feature_frame):
        """Return probability (0-1) that irrigation is needed.

        Handles single-class edge cases to avoid crashing when model was trained
        with limited labels.
        """
        model = self.models['watering']

        if not hasattr(model, "predict_proba"):
            return float(model.predict(feature_frame)[0])

        proba = model.predict_proba(feature_frame)[0]
        classes = list(getattr(model, "classes_", []))

        if not classes:
            return float(np.max(proba))

        if 1 in classes:
            return float(proba[classes.index(1)])

        return float(model.predict(feature_frame)[0])

    @staticmethod
    def _confidence_band(score):
        if score >= 85:
            return "Very High"
        if score >= 70:
            return "High"
        if score >= 55:
            return "Moderate"
        return "Low"

    def _build_explainability_factors(self, current_temp, current_hum, current_light, current_moisture, moisture_delta):
        factors = []

        if current_moisture < 35:
            factors.append({"label": "Soil moisture", "impact": "high", "detail": "Soil moisture is below 35%, indicating dry root-zone conditions."})
        elif current_moisture < 45:
            factors.append({"label": "Soil moisture", "impact": "medium", "detail": "Soil moisture is trending toward the lower comfort band."})
        else:
            factors.append({"label": "Soil moisture", "impact": "low", "detail": "Soil moisture is within a healthy operating band."})

        if moisture_delta <= -2.0:
            factors.append({"label": "Moisture slope", "impact": "medium", "detail": "Recent moisture readings are dropping, suggesting ongoing water loss."})
        elif moisture_delta >= 2.0:
            factors.append({"label": "Moisture slope", "impact": "low", "detail": "Moisture has recovered in recent readings."})

        if current_temp >= 33:
            factors.append({"label": "Temperature load", "impact": "medium", "detail": "Higher temperature increases evaporation pressure."})

        if current_hum <= 45:
            factors.append({"label": "Air dryness", "impact": "medium", "detail": "Lower humidity can accelerate moisture loss from soil."})

        if current_light >= 700:
            factors.append({"label": "Solar intensity", "impact": "low", "detail": "Strong light may increase daytime transpiration demand."})

        return factors[:4]

    def _compose_human_summary(self, recommendation, risk_level, rec_hours, anomaly_detected):
        if recommendation["priority"] == "high":
            return "The system sees clear dry-risk signals. Irrigate soon to protect root moisture stability."
        if recommendation["priority"] == "medium" and rec_hours > 0:
            return f"Conditions are still manageable, but dryness is building. Plan irrigation in about {rec_hours} hour(s)."
        if anomaly_detected:
            return "Sensor patterns changed abruptly, so the system recommends verification before aggressive pump changes."
        if risk_level == "LOW":
            return "Conditions are stable. Continue the current schedule and monitor as normal."
        return "The environment is in a watch state. Keep monitoring and reassess after the next sensor cycle."

    def _build_recommendation(self, watering_needed, risk_score, rec_hours, temp_trend, hum_trend, anomaly_detected):
        if watering_needed or risk_score >= 75:
            return {
                "priority": "high",
                "action": "Irrigate soon",
                "recommendation_text": "Soil is in a dry-risk zone. Trigger irrigation in the next 30-60 minutes and recheck moisture.",
            }
        if risk_score >= 55:
            return {
                "priority": "medium",
                "action": "Prepare irrigation",
                "recommendation_text": f"Dryness risk is building. Plan irrigation in about {max(rec_hours, 1)} hour(s) and monitor trend slope.",
            }
        if anomaly_detected:
            return {
                "priority": "medium",
                "action": "Monitor sensor integrity",
                "recommendation_text": "Abrupt environmental shifts detected. Validate sensor stability before applying aggressive irrigation changes.",
            }
        if temp_trend == "Rising" and hum_trend == "Falling":
            return {
                "priority": "low",
                "action": "Increase watch frequency",
                "recommendation_text": "Hot-dry drift detected. Keep closer watch on moisture and reevaluate in 1 hour.",
            }
        return {
            "priority": "low",
            "action": "Hold steady",
            "recommendation_text": "Conditions are currently stable. Continue current irrigation schedule.",
        }

    def get_summary(self, latest_sensors, latest_soil):
        if not self.models:
            return {"error": "Models not loaded"}
        
        if len(latest_sensors) < 4 or len(latest_soil) < 3:
            return {
                "error": "Insufficient sequence depth for stable inference",
                "needs_more_data": True,
            }

        # Prepare inputs with key-fallback support for historical schema differences.
        current_temp = self._pick_value(latest_sensors[0], "temperature")
        current_hum = self._pick_value(latest_sensors[0], "humidity", "pressure")
        current_light = self._pick_value(latest_sensors[0], "light_intensity", "lightIntensity")
        current_moisture = self._pick_value(latest_soil[0], "moisture")
        current_hour = datetime.now().hour

        recent_temp = [self._pick_value(s, "temperature") for s in latest_sensors[:6]]
        recent_hum = [self._pick_value(s, "humidity", "pressure") for s in latest_sensors[:6]]
        recent_moisture = [self._pick_value(s, "moisture") for s in latest_soil[:6]]
        moisture_delta = recent_moisture[0] - recent_moisture[min(2, len(recent_moisture) - 1)]
        
        # Temperature Trend
        temp_lags = [self._pick_value(latest_sensors[i], "temperature") for i in range(1, 4)]
        X_temp = pd.DataFrame([temp_lags], columns=['temperature_lag_1', 'temperature_lag_2', 'temperature_lag_3'])
        temp_pred = self.models['temp_trend'].predict(X_temp)[0]
        temp_diff = temp_pred - current_temp
        temp_trend_text = self._trend_label(temp_diff, 0.2, -0.2)
        
        # Humidity Trend
        hum_lags = [self._pick_value(latest_sensors[i], "humidity", "pressure") for i in range(1, 4)]
        X_hum = pd.DataFrame([hum_lags], columns=['pressure_lag_1', 'pressure_lag_2', 'pressure_lag_3'])
        hum_pred = self.models['hum_trend'].predict(X_hum)[0]
        hum_diff = hum_pred - current_hum
        hum_trend_text = self._trend_label(hum_diff, 1.0, -1.0)
        
        # Watering Prediction
        X_water = pd.DataFrame([[current_temp, current_hum, current_light, current_moisture, current_hour]], 
                               columns=['temperature', 'pressure', 'light_intensity', 'moisture', 'hour'])
        watering_probability = self._compute_watering_probability(X_water)

        dryness_risk = self._compute_dryness_risk(
            current_temp=current_temp,
            current_hum=current_hum,
            current_light=current_light,
            current_moisture=current_moisture,
            moisture_delta=moisture_delta,
        )

        # A lightweight anomaly marker from abrupt deltas in recent streams.
        temp_jump = abs(recent_temp[0] - recent_temp[min(2, len(recent_temp) - 1)])
        hum_jump = abs(recent_hum[0] - recent_hum[min(2, len(recent_hum) - 1)])
        anomaly_detected = temp_jump > 4.0 or hum_jump > 12.0
        
        # Heuristic for hours based on moisture levels if not immediately needed
        blended_need_score = (watering_probability * 100.0 * 0.55) + (dryness_risk * 0.45)
        if anomaly_detected:
            blended_need_score += 4.0

        water_needed_bool = blended_need_score >= 58.0 or dryness_risk >= 75

        rec_hours = 0
        if water_needed_bool:
            rec_hours = 0
        else:
            if current_moisture > 60: rec_hours = 8
            elif current_moisture > 45: rec_hours = 4
            else: rec_hours = 2

        recommendation = self._build_recommendation(
            watering_needed=water_needed_bool,
            risk_score=dryness_risk,
            rec_hours=rec_hours,
            temp_trend=temp_trend_text,
            hum_trend=hum_trend_text,
            anomaly_detected=anomaly_detected,
        )

        confidence_center = abs(blended_need_score - 58.0)
        effective_confidence = 0.52 + min(confidence_center / 120.0, 0.35)
        if anomaly_detected:
            effective_confidence *= 0.92
        if dryness_risk >= 75:
            effective_confidence = max(effective_confidence, 0.82)

        explainability_factors = self._build_explainability_factors(
            current_temp=current_temp,
            current_hum=current_hum,
            current_light=current_light,
            current_moisture=current_moisture,
            moisture_delta=moisture_delta,
        )

        confidence_pct = round(effective_confidence * 100, 1)
        human_summary = self._compose_human_summary(
            recommendation=recommendation,
            risk_level="HIGH" if dryness_risk >= 75 else "MEDIUM" if dryness_risk >= 55 else "LOW",
            rec_hours=rec_hours,
            anomaly_detected=anomaly_detected,
        )
        
        return {
            "watering_needed": water_needed_bool,
            "recommended_in_hours": rec_hours,
            "confidence": confidence_pct,
            "temp_trend": temp_trend_text,
            "temp_diff": round(float(temp_diff), 1),
            "temp_pred": round(float(temp_pred), 1),
            "hum_trend": hum_trend_text,
            "hum_diff": round(float(hum_diff), 1),
            "hum_pred": round(float(hum_pred), 1),
            "risk_score": dryness_risk,
            "risk_level": "HIGH" if dryness_risk >= 75 else "MEDIUM" if dryness_risk >= 55 else "LOW",
            "anomaly_detected": anomaly_detected,
            "recommendation_priority": recommendation["priority"],
            "recommended_action": recommendation["action"],
            "recommendation_text": recommendation["recommendation_text"],
            "watering_probability": round(watering_probability * 100, 1),
            "blended_need_score": round(blended_need_score, 1),
            "confidence_band": self._confidence_band(confidence_pct),
            "insight_summary": human_summary,
            "insight_factors": explainability_factors,
            "next_review_minutes": 30 if water_needed_bool else 60,
            "model_version": "v2.2-explainable-hybrid",
            "timestamp": datetime.now().isoformat()
        }

# Global instance
engine = PredictionEngine()
