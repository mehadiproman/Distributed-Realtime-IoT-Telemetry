import sys
import os
import pandas as pd
import numpy as np
import asyncio
import joblib
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestClassifier

# Add parent directory to path to import database config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

async def get_training_data():
    """Fetch data from DB and convert to DataFrame"""
    await database.init_db()
    
    sensors = await database.get_all_sensor_data(limit=1000)
    soil = await database.get_all_soil_data(limit=1000)
    
    if len(sensors) < 5 or len(soil) < 5:
        print("Not enough data in DB. Generating synthetic training data...")
        return generate_synthetic_data()
    
    df_sensors = pd.DataFrame(sensors)
    df_soil = pd.DataFrame(soil)
    
    # Merge on nearest timestamp
    df_sensors['timestamp'] = pd.to_datetime(df_sensors['timestamp'])
    df_soil['timestamp'] = pd.to_datetime(df_soil['timestamp'])
    
    df = pd.merge_asof(
        df_sensors.sort_values('timestamp'),
        df_soil.sort_values('timestamp'),
        on='timestamp',
        direction='nearest',
        suffixes=('', '_soil')
    )
    return df

def generate_synthetic_data():
    """Create fake data that simulates daily cycles and irrigation"""
    now = datetime.now()
    times = [now - timedelta(minutes=10*i) for i in range(500)]
    
    data = []
    for t in times:
        hour = t.hour
        # Temp cycle (hotter at mid-day)
        temp = 25 + 10 * np.sin((hour - 6) * np.pi / 12) + np.random.normal(0, 0.5)
        # Hum inverse cycle
        hum = 60 - 20 * np.sin((hour - 6) * np.pi / 12) + np.random.normal(0, 2)
        # Light cycle
        light = max(0, 800 * np.sin((hour - 6) * np.pi / 12)) + np.random.normal(0, 10)
        # Soil moisture (gradually decreases, jumps on 'pump_on' events simulated)
        moisture = 40 + np.random.normal(0, 1)
        
        data.append({
            'timestamp': t,
            'temperature': temp,
            'pressure': hum, # Using pressure as humidity per project convention
            'light_intensity': light,
            'moisture': moisture
        })
    
    return pd.DataFrame(data)

def train_trend_model(df, field, model_name):
    """Train a simple linear regression to predict next value based on previous sequence"""
    # Create lag features
    for i in range(1, 4):
        df[f'{field}_lag_{i}'] = df[field].shift(i)
    
    df = df.dropna()
    
    X = df[[f'{field}_lag_{i}' for i in range(1, 4)]]
    y = df[field]
    
    model = LinearRegression()
    model.fit(X, y)
    
    joblib.dump(model, os.path.join(MODEL_DIR, f"{model_name}.pkl"))
    print(f"Trained trend model for {field}")

def train_watering_model(df):
    """Train RF to predict if watering is needed (binary) and confidence"""
    # Feature engineering
    df['hour'] = df['timestamp'].dt.hour
    
    # Target: 1 if moisture < 35, else 0 (Simple rule-based target for training synthetic demo)
    df['need_watering'] = (df['moisture'] < 35).astype(int)
    
    # In real world, we'd use future records to see if watering WAS done.
    # For this beginner-friendly version, we use current state + trends.
    
    X = df[['temperature', 'pressure', 'light_intensity', 'moisture', 'hour']]
    y = df['need_watering']
    
    model = RandomForestClassifier(n_estimators=50)
    model.fit(X, y)
    
    joblib.dump(model, os.path.join(MODEL_DIR, "watering_model.pkl"))
    print("Trained watering prediction model")

async def main():
    if not os.path.exists(MODEL_DIR):
        os.makedirs(MODEL_DIR)
        
    df = await get_training_data()
    
    # Train Temperature Trend
    train_trend_model(df, 'temperature', "temp_trend")
    # Train Humidity Trend 
    train_trend_model(df, 'pressure', "hum_trend")
    # Train Watering model
    train_watering_model(df)
    
    print("All models trained and saved to ml/models/")

if __name__ == "__main__":
    asyncio.run(main())
