# Multimodal AI Dataset Configuration

This document describes the dataset configuration for the table tennis AI/coaching system.

## Overview

The system uses public datasets for:
- **Voice Core**: ASR, intent classification, anti-spoofing
- **Table Tennis Perception Core**: Ball detection, stroke classification, trajectory reconstruction
- **Coaching Core**: Technique analysis, feedback generation

## External Storage Structure

Real datasets must be stored **outside the repository** in a dedicated data directory. This prevents large binary files from being committed to version control.

### Recommended Directory Structure

```
tt_ai_data/
├── raw/
│   ├── voice/
│   │   ├── common_voice/
│   │   ├── gigaspeech/
│   │   ├── librispeech/
│   │   ├── ami/
│   │   ├── fluent_speech_commands/
│   │   └── asvspoof2021/
│   └── table_tennis/
│       ├── t3set/
│       ├── openttgames/
│       ├── extended_openttgames/
│       ├── blurball/
│       ├── ttswing/
│       └── tt3d/
├── processed/
├── features/
├── indexes/
│   └── chroma_multimodal/
├── models/
├── cache/
└── manifests/
```

## Environment Configuration

Create a `.env` file in the project root with the following variables:

### Linux/macOS Example
```bash
# External data storage
TT_DATA_ROOT=../tt_ai_data
TT_RAW_DATA_DIR=../tt_ai_data/raw
TT_PROCESSED_DATA_DIR=../tt_ai_data/processed
TT_FEATURES_DIR=../tt_ai_data/features
TT_MODELS_DIR=../tt_ai_data/models
TT_CACHE_DIR=../tt_ai_data/cache
TT_MANIFESTS_DIR=../tt_ai_data/manifests
TT_MULTIMODAL_CHROMA_DIR=../tt_ai_data/indexes/chroma_multimodal
```

### Windows Example
```bash
# External data storage
TT_DATA_ROOT=D:/datasets/tt_ai_data
TT_RAW_DATA_DIR=D:/datasets/tt_ai_data/raw
TT_PROCESSED_DATA_DIR=D:/datasets/tt_ai_data/processed
TT_FEATURES_DIR=D:/datasets/tt_ai_data/features
TT_MODELS_DIR=D:/datasets/tt_ai_data/models
TT_CACHE_DIR=D:/datasets/tt_ai_data/cache
TT_MANIFESTS_DIR=D:/datasets/tt_ai_data/manifests
TT_MULTIMODAL_CHROMA_DIR=D:/datasets/tt_ai_data/indexes/chroma_multimodal
```

## Dataset Download Order

For initial development, download datasets in this order:

1. **TTSwing** - Sensor data for stroke analysis (MIT license, commercial-safe)
2. **OpenTTGames + Extended OpenTTGames** - Ball detection and stroke labels
3. **TT3D** - 3D trajectory data
4. **Common Voice** - Selected languages for multilingual ASR
5. **LibriSpeech** - Clean speech for benchmarking (or small GigaSpeech subset)
6. **AMI** - Conversational speech for robustness
7. **T3Set** - Coaching text and video (non-commercial)
8. **BlurBall** - Blurred ball tracking
9. **Fluent Speech Commands + ASVspoof 2021** - When voice-command/auth work starts

## License Warnings

### Non-Commercial / Research-Only Datasets
- **T3Set** - Coaching/recommendation dataset
- **OpenTTGames-family** - Ball detection and stroke datasets
- **Fluent Speech Commands** - Command/intent dataset

These datasets are marked as `non_commercial` or `research_only` in the manifest. They should be treated as **research-only** unless manually verified for commercial use.

### Unknown License Datasets
- **P2ANet**
- **RacketVision**
- **TTST**
- **VoxCeleb2**
- **IEMOCAP**
- **AudioSet**
- **SoccerNet-Echoes**

These datasets are marked as `unknown` license. They should be **blocked for commercial use** until reviewed.

## Validation

Use the validation script to check dataset availability:

```bash
# List available presets
python scripts/validate_datasets.py --list-presets

# Validate a specific preset
python scripts/validate_datasets.py --preset voice_core
python scripts/validate_datasets.py --preset tt_perception_core
python scripts/validate_datasets.py --preset coaching_core

# Validate all datasets
python scripts/validate_datasets.py --all
```

### Validation Status Codes

- **FOUND** - Dataset directory exists and is accessible
- **MISSING** - Dataset directory does not exist
- **LICENSE_RESTRICTED** - Dataset exists but has non-commercial license
- **COMMERCIAL_UNKNOWN** - Dataset exists but license is unknown

## .gitignore

The following patterns are ignored to prevent committing large data files:

```gitignore
# Multimodal AI - Large data files
tt_ai_data/
**/raw/
**/processed/
**/features/
**/models/
**/cache/
# Model weights
*.pt
*.bin
*.onnx
# Large binary files
*.h5
*.ckpt
# Media files
*.mp4
*.avi
*.mov
*.wav
*.flac
*.mp3
# Archives
*.zip
*.tar
*.tar.gz
```

## Dataset Manifest

The dataset manifest is located at:
- `tournament_platform/multimodal_ai/manifests/datasets.yaml`

It contains:
- All supported dataset definitions
- Dataset combination presets
- License and commercial use information

## Integration with Existing System

The dataset configuration integrates with:
- **SQLAlchemy models** - `Dataset`, `DatasetArtifact`, `DataSample` tables
- **API endpoints** - `/api/datasets`, `/api/datasets/validate`
- **Streamlit UI** - Dataset Catalog page
- **Feature extraction** - Adapter pattern for each dataset type