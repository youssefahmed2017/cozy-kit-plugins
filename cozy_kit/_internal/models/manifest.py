from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str
    author: str
    methods: List[str]
    target: Optional[str] = None
    engine_path: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    license: Optional[str] = None
    min_cozy_kit_version: Optional[str] = None
    python_requires: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    conflict_with: List[str] = field(default_factory=list)
    clis: Dict[str, str] = field(default_factory=dict)
    official: bool = False
    builtin: bool = False
