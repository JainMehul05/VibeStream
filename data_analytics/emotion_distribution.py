@'
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAIN_DATA_PATH = PROJECT_ROOT / "ai_ml" / "data" / "training.csv"
VISUALIZATIONS_DIR = PROJECT_ROOT / "data_analytics" / "visualizations"

VISUALIZATIONS_DIR.mkdir(parents=True, exist_ok=True)

if not TRAIN_DATA_PATH.exists():
    raise FileNotFoundError(f"Training data not found: {TRAIN_DATA_PATH}")

df = pd.read_csv(TRAIN_DATA_PATH)

emotion_mapping = {
    0: "sadness",
    1: "joy",
    2: "love",
    3: "anger",
    4: "fear",
}

df["emotion"] = df["label"].map(emotion_mapping)

plt.figure(figsize=(10, 6))
df["emotion"].value_counts().plot(
    kind="bar",
    color="skyblue",
    edgecolor="black",
)

plt.title("Emotion Distribution in Training Dataset")
plt.xlabel("Emotions")
plt.ylabel("Frequency")
plt.xticks(rotation=45)
plt.tight_layout()

output_path = VISUALIZATIONS_DIR / "emotion_distribution.png"
plt.savefig(output_path)
print(f"Saved visualization to: {output_path}")

plt.show()
'@ | Set-Content "data_analytics/emotion_distribution.py"