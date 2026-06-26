from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PluginContext:
    """Passed to every lifecycle hook so hooks know about the plugin they belong to."""

    name: str
    version: str
    description: str
    author: str
    methods: List[str]
    target: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
