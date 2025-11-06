"""
Pytest configuration and fixtures for facesort testing.
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator, List, Optional
import pytest
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from cluster_simple import ArcFaceEmbedder, ArcFaceConfig, is_image, imread_safe


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Path to test data directory."""
    return Path("/Users/artembutko/Desktop/116_Даша-1/Младшая")


@pytest.fixture(scope="session")
def test_images_dir(test_data_dir: Path) -> Path:
    """Directory with test images."""
    return test_data_dir


@pytest.fixture(scope="session")
def test_common_dir(test_data_dir: Path) -> Path:
    """Directory with common photos."""
    return test_data_dir / "общие"


@pytest.fixture(scope="session")
def test_images(test_images_dir: Path) -> List[Path]:
    """List of test image files."""
    if not test_images_dir.exists():
        pytest.skip(f"Test images directory not found: {test_images_dir}")
    
    images = []
    for ext in [".jpg", ".jpeg", ".png"]:
        images.extend(test_images_dir.glob(f"*{ext}"))
        images.extend(test_images_dir.glob(f"*{ext.upper()}"))
    
    if not images:
        pytest.skip("No test images found")
    
    return images[:5]  # Limit to 5 images for faster testing


@pytest.fixture(scope="session")
def test_common_images(test_common_dir: Path) -> List[Path]:
    """List of common photo files."""
    if not test_common_dir.exists():
        pytest.skip(f"Test common directory not found: {test_common_dir}")
    
    images = []
    for ext in [".jpg", ".jpeg", ".png"]:
        images.extend(test_common_dir.glob(f"*{ext}"))
        images.extend(test_common_dir.glob(f"*{ext.upper()}"))
    
    if not images:
        pytest.skip("No common images found")
    
    return images[:3]  # Limit to 3 images for faster testing


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def temp_images_dir(temp_dir: Path) -> Path:
    """Temporary directory for test images."""
    images_dir = temp_dir / "images"
    images_dir.mkdir()
    return images_dir


@pytest.fixture
def sample_image_path(temp_images_dir: Path) -> Path:
    """Create a sample test image."""
    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='red')
    img_path = temp_images_dir / "test_image.jpg"
    img.save(img_path)
    return img_path


@pytest.fixture
def sample_image_with_face(temp_images_dir: Path) -> Path:
    """Create a sample image that might contain a face (placeholder)."""
    # Create a more realistic test image
    img = Image.new('RGB', (200, 200), color='white')
    img_path = temp_images_dir / "face_image.jpg"
    img.save(img_path)
    return img_path


@pytest.fixture
def corrupted_image_path(temp_images_dir: Path) -> Path:
    """Create a corrupted image file."""
    img_path = temp_images_dir / "corrupted.jpg"
    with open(img_path, 'wb') as f:
        f.write(b"not a valid image")
    return img_path


@pytest.fixture
def unicode_path(temp_dir: Path) -> Path:
    """Create a directory with Unicode (Cyrillic) name."""
    unicode_dir = temp_dir / "тестовая_папка"
    unicode_dir.mkdir()
    return unicode_dir


@pytest.fixture(scope="session")
def arcface_embedder() -> ArcFaceEmbedder:
    """ArcFace embedder for testing."""
    try:
        config = ArcFaceConfig(ctx_id=-1, det_size=(320, 320))  # CPU, smaller size for speed
        return ArcFaceEmbedder(config)
    except ImportError as e:
        pytest.skip(f"ArcFace not available: {e}")


@pytest.fixture
def fastapi_client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_plan() -> dict:
    """Mock clustering plan for testing."""
    return {
        "plan": [
            {
                "path": "/test/image1.jpg",
                "cluster": [0],
                "faces": 1
            },
            {
                "path": "/test/image2.jpg", 
                "cluster": [0],
                "faces": 1
            },
            {
                "path": "/test/image3.jpg",
                "cluster": [1],
                "faces": 1
            }
        ],
        "clusters": {
            "0": {"count": 2, "faces": 2},
            "1": {"count": 1, "faces": 1}
        },
        "stats": {
            "total_images": 3,
            "total_faces": 3,
            "clusters_count": 2
        }
    }


@pytest.fixture
def mock_common_plan() -> dict:
    """Mock plan for common photos testing."""
    return {
        "plan": [
            {
                "path": "/test/общие/group1.jpg",
                "cluster": [0, 1, 2],
                "faces": 3
            },
            {
                "path": "/test/общие/group2.jpg",
                "cluster": [0, 1],
                "faces": 2
            }
        ],
        "clusters": {
            "0": {"count": 2, "faces": 2},
            "1": {"count": 2, "faces": 2}, 
            "2": {"count": 1, "faces": 1}
        },
        "stats": {
            "total_images": 2,
            "total_faces": 5,
            "clusters_count": 3
        }
    }


@pytest.fixture
def test_folder_structure(temp_dir: Path) -> dict:
    """Create a test folder structure."""
    # Create main folder
    main_folder = temp_dir / "test_photos"
    main_folder.mkdir()
    
    # Create subfolders
    person1 = main_folder / "person1"
    person2 = main_folder / "person2"
    common = main_folder / "общие"
    
    person1.mkdir()
    person2.mkdir()
    common.mkdir()
    
    # Create some test files
    (person1 / "photo1.jpg").touch()
    (person1 / "photo2.jpg").touch()
    (person2 / "photo3.jpg").touch()
    (common / "group1.jpg").touch()
    (common / "group2.jpg").touch()
    
    return {
        "main": main_folder,
        "person1": person1,
        "person2": person2,
        "common": common
    }


@pytest.fixture
def cleanup():
    """Cleanup fixture for any test-specific cleanup."""
    yield
    # Any cleanup code can go here


# Pytest markers
pytestmark = pytest.mark.asyncio
