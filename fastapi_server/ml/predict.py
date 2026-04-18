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

    def get_summary(self, latest_sensors, latest_soil):
        if not self.models:
            return {"error": "Models not loaded"}
        
        # Prepare inputs
        current_temp = latest_sensors[0]['temperature']
        current_hum = latest_sensors[0]['pressure'] # convention
        current_light = latest_sensors[0]['light_intensity']
        current_moisture = latest_soil[0]['moisture']
        current_hour = datetime.now().hour
        
        # Temperature Trend
        temp_lags = [latest_sensors[i]['temperature'] for i in range(1, 4)]
        temp_pred = self.models['temp_trend'].predict(np.array([temp_lags]))[0]
        temp_diff = temp_pred - current_temp
        temp_trend_text = "Rising" if temp_diff > 0.2 else "Falling" if temp_diff < -0.2 else "Stable"
        
        # Humidity Trend
        hum_lags = [latest_sensors[i]['pressure'] for i in range(1, 4)]
        hum_pred = self.models['hum_trend'].predict(np.array([hum_lags]))[0]
        hum_diff = hum_pred - current_hum
        hum_trend_text = "Rising" if hum_diff > 1 else "Falling" if hum_diff < -1 else "Stable"
        
        # Watering Prediction
        X_water = pd.DataFrame([[current_temp, current_hum, current_light, current_moisture, current_hour]], 
                               columns=['temperature', 'pressure', 'light_intensity', 'moisture', 'hour'])
        water_needed_bool = bool(self.models['watering'].predict(X_water)[0])
        water_confidence = self.models['watering'].predict_proba(X_water)[0].max()
        
        # Heuristic for hours based on moisture levels if not immediately needed
        rec_hours = 0
        if not water_needed_bool:
            if current_moisture > 60: rec_hours = 8
            elif current_moisture > 45: rec_hours = 4
            else: rec_hours = 2
        
        return {
            "watering_needed": water_needed_bool,
            "recommended_in_hours": rec_hours,
            "confidence": round(float(water_confidence) * 100, 1),
            "temp_trend": temp_trend_text,
            "temp_diff": round(float(temp_diff), 1),
            "temp_pred": round(float(temp_pred), 1),
            "hum_trend": hum_trend_text,
            "hum_diff": round(float(hum_diff), 1),
            "hum_pred": round(float(hum_pred), 1),
            "timestamp": datetime.now().isoformat()
        }

# Global instance
engine = PredictionEngine()
