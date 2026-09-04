@'
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_LOG_PATH = (
    PROJECT_ROOT
    / "ai_ml"
    / "models"
    / "text_emotion_model"
    / "training_log.csv"
)
VISUALIZATIONS_DIR = PROJECT_ROOT / "data_analytics" / "visualizations"

VISUALIZATIONS_DIR.mkdir(parents=True, exist_ok=True)

if not TRAINING_LOG_PATH.exists():
    raise FileNotFoundError(
        f"Training log file not found: {TRAINING_LOG_PATH}"
    )

df = pd.read_csv(TRAINING_LOG_PATH)

plt.figure(figsize=(10, 6))
plt.plot(df["epoch"], df["loss"], label="Training Loss")

if "eval_loss" in df.columns:
    plt.plot(df["epoch"], df["eval_loss"], label="Validation Loss")

plt.title("Training and Validation Loss")
plt.xlabel("Epoch")
plt.ylabel("Loss")
plt.legend()
plt.grid(True)
plt.tight_layout()

loss_output = VISUALIZATIONS_DIR / "loss_curve.png"
plt.savefig(loss_output)
print(f"Saved loss curve to: {loss_output}")

plt.show()

plt.figure(figsize=(10, 6))

if "eval_accuracy" in df.columns and "accuracy" in df.columns:
    plt.plot(df["epoch"], df["accuracy"], label="Train Accuracy")
    plt.plot(
        df["epoch"],
        df["eval_accuracy"],
        label="Validation Accuracy",
    )

plt.title("Training and Validation Accuracy")
plt.xlabel("Epoch")
plt.ylabel("Accuracy")
plt.legend()
plt.grid(True)
plt.tight_layout()

accuracy_output = VISUALIZATIONS_DIR / "accuracy_curve.png"
plt.savefig(accuracy_output)
print(f"Saved accuracy curve to: {accuracy_output}")

plt.show()
'@ | Set-Content "data_analytics/training_visualization.py"