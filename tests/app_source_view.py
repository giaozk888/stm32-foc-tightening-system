"""Historical source checks inspect the real App A split bodies, not a backup."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from app_a_source_layout import read_app_source
