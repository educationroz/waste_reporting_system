import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models, transforms
from PIL import Image
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'gatekeeper_model.pth')

# Django/web server ma usually GPU hudaina, tara xa bhane use garcha
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

# ⚠️ Training script (train_gatekeeper.py) sanga EXACTLY match garने architecture
def build_model():
    model = models.mobilenet_v3_small()  # weights=None — pretrained hoina, tapaiको trained weights load huнेछ
    num_ftrs = model.classifier[3].in_features
    model.classifier[3] = nn.Sequential(
        nn.Dropout(0.5),
        nn.Linear(num_ftrs, 4)
    )
    return model

_model = None  # process ma ek patak matra load huos (singleton)

def get_model():
    global _model
    if _model is None:
        model = build_model()
        state_dict = torch.load(MODEL_PATH, map_location=device)
        model.load_state_dict(state_dict)
        model = model.to(device)
        model.eval()
        _model = model
    return _model

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

# Alphabetical ImageFolder order sanga match — testing script bata copy gareko
CLASS_LABELS = [
    {'raw': 'high', 'display': 'High Waste', 'is_waste': True, 'severity': 'high'},
    {'raw': 'invalid', 'display': 'Invalid / Clean Place', 'is_waste': False, 'severity': None},
    {'raw': 'low', 'display': 'Low Waste', 'is_waste': True, 'severity': 'low'},
    {'raw': 'medium', 'display': 'Medium Waste', 'is_waste': True, 'severity': 'medium'},
]

LOW_CONFIDENCE_THRESHOLD = 45.0  # tapaiको testing script bata


def predict_waste(image_path_or_file):
    """
    image_path_or_file: file path (str) or file-like object (InMemoryUploadedFile / Django FieldFile)
    Returns dict: is_waste, severity, confidence, display_label, needs_manual_review
    """
    model = get_model()
    image = Image.open(image_path_or_file).convert('RGB')
    input_tensor = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        outputs = model(input_tensor)
        probabilities = F.softmax(outputs, dim=1)
        confidence, predicted_idx = torch.max(probabilities, 1)

    idx = predicted_idx.item()
    confidence_pct = round(confidence.item() * 100, 2)
    class_info = CLASS_LABELS[idx]

    return {
        'is_waste': class_info['is_waste'],
        'severity': class_info['severity'],
        'display_label': class_info['display'],
        'confidence': confidence_pct,
        'needs_manual_review': confidence_pct < LOW_CONFIDENCE_THRESHOLD,
    }