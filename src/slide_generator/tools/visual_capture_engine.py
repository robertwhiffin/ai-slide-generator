"""Enhanced visual capture engine for robust chart detection.

This module provides priority-based container-level capture that works with any
visualization type (CSS charts, Canvas charts, SVG charts, custom dashboards).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Set, Dict, Tuple, Optional
from enum import Enum


class CaptureStrategy(Enum):
    CONTAINER_PRIORITY = "container_first"
    SEMANTIC_ANALYSIS = "semantic_detection" 
    SPATIAL_INTELLIGENCE = "collision_detection"


@dataclass
class VisualizationArea:
    """Represents a captured visualization area with metadata."""
    selector: str
    bounding_box: Dict[str, float]  # {x, y, width, height}
    element_type: str
    priority_level: int
    screenshot_data: bytes
    slide_index: int
    confidence_score: float  # 0.0-1.0 how confident this is a complete visualization
    
    @property
    def width(self) -> int:
        return int(self.bounding_box['width'])
    
    @property
    def height(self) -> int:
        return int(self.bounding_box['height'])


class SpatialCollisionDetector:
    """Detects and prevents overlapping/nested captures."""
    
    def __init__(self):
        self.occupied_regions: List[Tuple[float, float, float, float]] = []
        
    def is_area_available(self, x: float, y: float, width: float, height: float, 
                         min_overlap_threshold: float = 0.3) -> bool:
        """Check if area is available for capture (not significantly overlapping)."""
        new_area = (x, y, x + width, y + height)
        
        for occupied in self.occupied_regions:
            overlap_ratio = self._calculate_overlap_ratio(new_area, occupied)
            if overlap_ratio > min_overlap_threshold:
                self._log_debug(f"Area collision detected: {overlap_ratio:.2f} overlap > {min_overlap_threshold}")
                return False
        return True
    
    def register_captured_area(self, x: float, y: float, width: float, height: float):
        """Register an area as captured."""
        self.occupied_regions.append((x, y, x + width, y + height))
        self._log_debug(f"Registered area: ({x}, {y}) {width}x{height}")
        
    def _calculate_overlap_ratio(self, area1: Tuple, area2: Tuple) -> float:
        """Calculate overlap ratio between two rectangular areas."""
        x1_min, y1_min, x1_max, y1_max = area1
        x2_min, y2_min, x2_max, y2_max = area2
        
        # Calculate intersection
        int_x_min = max(x1_min, x2_min)
        int_y_min = max(y1_min, y2_min)
        int_x_max = min(x1_max, x2_max)
        int_y_max = min(y1_max, y2_max)
        
        if int_x_max <= int_x_min or int_y_max <= int_y_min:
            return 0.0  # No overlap
            
        intersection_area = (int_x_max - int_x_min) * (int_y_max - int_y_min)
        area1_size = (x1_max - x1_min) * (y1_max - y1_min)
        
        return intersection_area / area1_size if area1_size > 0 else 0.0
    
    def _log_debug(self, message: str):
        """Log debug message if debug mode is enabled."""
        if os.getenv('VISUAL_CAPTURE_DEBUG') == 'true':
            print(f"🔍 CollisionDetector: {message}")


class VisualizationCaptureEngine:
    """Advanced capture engine with container-first intelligence."""
    
    def __init__(self):
        self.captured_areas: Set[str] = set()
        self.priority_selectors = self._build_priority_selectors()
        self.collision_detector = SpatialCollisionDetector()
        
    def _build_priority_selectors(self) -> Dict[int, List[str]]:
        """Build priority-based selector dictionary."""
        return {
            1: [  # P1: Explicit visualization containers (90% confidence)
                '.chart-container', '.visualization', '.plot-container', 
                '.dashboard', '.metrics-container', '.analytics-panel'
            ],
            2: [  # P2: Semantic containers (80% confidence) 
                'div[class*="chart"]', 'div[id*="chart"]',
                'div[class*="plot"]', 'div[id*="plot"]',
                'div[class*="graph"]', 'div[class*="visual"]',
                '.custom-content'  # Known custom visualization area
            ],
            3: [  # P3: Layout-based detection (70% confidence)
                'div[style*="display: flex"][style*="justify-content: center"][style*="height:"]',
                'div[style*="text-align: center"][style*="height:"][style*="width:"]',
                'div[style*="position: relative"][style*="height:"][style*="background"]'
            ],
            4: [  # P4: Library-specific wrappers (60% confidence)
                '.plotly-graph-div', '.d3-chart', '.recharts-wrapper',
                '.highcharts-container', '.apexcharts-canvas', '.chartjs-container'
            ],
            5: [  # P5: Individual elements - ONLY if no containers found (30% confidence)
                'svg:not(.captured)', 'canvas:not(.captured)'
            ]
        }
    
    def get_enhanced_element_type(self, selector: str, box: Dict) -> str:
        """Enhanced element type classification with context awareness."""
        
        # Aspect ratio analysis
        aspect_ratio = box['width'] / box['height'] if box['height'] > 0 else 1
        width, height = box['width'], box['height']
        
        # Logo detection (size + position based)
        if ('logo' in selector.lower() or 
            (width < 200 and height < 100 and 
             (box['x'] > width * 0.7 or box['y'] > height * 0.8))):
            return 'logo'
        
        # Dashboard detection (large + complex)
        if width > 800 and height > 600:
            return 'dashboard'
        
        # Horizontal bar chart detection (wide + moderate height)
        if aspect_ratio > 2.5 and height > 200 and height < 600:
            return 'horizontal_bar_chart'
        
        # Vertical chart detection (tall + moderate width)
        if aspect_ratio < 0.8 and width > 200 and width < 600:
            return 'vertical_chart'
        
        # Square/pie chart detection
        if 0.8 <= aspect_ratio <= 1.25 and min(width, height) > 300:
            return 'pie_or_square_chart'
        
        # Library-specific detection
        lib_types = {
            'plotly': 'interactive_chart',
            'd3': 'd3_visualization', 
            'recharts': 'react_chart',
            'highcharts': 'interactive_chart',
            'apex': 'modern_chart',
            'custom-content': 'custom_visualization'
        }
        
        for lib, chart_type in lib_types.items():
            if lib in selector.lower():
                return chart_type
        
        # Fallback classification
        if 'svg' in selector:
            return 'svg_graphic'
        elif 'canvas' in selector:
            return 'canvas_chart'
        else:
            return 'container_visualization'

    def calculate_visualization_confidence(self, selector: str, box: Dict, priority: int) -> float:
        """Calculate confidence score for visualization detection."""
        
        base_confidence = {1: 0.9, 2: 0.8, 3: 0.7, 4: 0.6, 5: 0.3}[priority]
        
        # Size bonus (larger = more likely to be important visualization)
        size_area = box['width'] * box['height']
        size_bonus = min(0.15, size_area / 500000)  # Up to 15% bonus for large elements
        
        # Selector specificity bonus
        specificity_bonus = 0.0
        if 'chart' in selector.lower() or 'plot' in selector.lower():
            specificity_bonus += 0.1
        if 'container' in selector.lower() or 'wrapper' in selector.lower():
            specificity_bonus += 0.05
        
        # Aspect ratio penalty for extreme ratios (likely not charts)
        aspect_ratio = box['width'] / box['height'] if box['height'] > 0 else 1
        aspect_penalty = 0.0
        if aspect_ratio > 5 or aspect_ratio < 0.2:  # Very wide or very tall
            aspect_penalty = 0.2
        
        final_confidence = base_confidence + size_bonus + specificity_bonus - aspect_penalty
        return max(0.1, min(1.0, final_confidence))


class CaptureMetrics:
    """Tracks capture quality metrics for monitoring."""
    
    def __init__(self):
        self.total_elements_found = 0
        self.containers_captured = 0
        self.individual_elements_captured = 0
        self.collision_prevented_count = 0
        self.confidence_scores = []
        self.capture_time_ms = 0
        
    def add_capture(self, visualization: VisualizationArea, was_container: bool):
        """Record a successful capture."""
        self.confidence_scores.append(visualization.confidence_score)
        if was_container:
            self.containers_captured += 1
        else:
            self.individual_elements_captured += 1
    
    def add_collision_prevention(self):
        """Record that a collision was prevented."""
        self.collision_prevented_count += 1
    
    @property
    def avg_confidence_score(self) -> float:
        """Calculate average confidence score."""
        return sum(self.confidence_scores) / len(self.confidence_scores) if self.confidence_scores else 0.0
        
    def log_metrics(self):
        """Log capture metrics summary."""
        print(f"""
📊 ENHANCED CAPTURE METRICS:
   Total elements found: {self.total_elements_found}
   Containers captured: {self.containers_captured} 
   Individual elements: {self.individual_elements_captured}
   Collisions prevented: {self.collision_prevented_count}
   Avg confidence: {self.avg_confidence_score:.2f}
   Capture time: {self.capture_time_ms}ms
   Container success rate: {self.containers_captured / max(1, self.containers_captured + self.individual_elements_captured):.1%}
""")


class DebugMode:
    """Debug utilities for troubleshooting capture issues."""
    
    @staticmethod
    def log_capture_decision(element_info: str, selector: str, decision: str, reason: str):
        """Log capture decision if debug mode is enabled."""
        if os.getenv('VISUAL_CAPTURE_DEBUG') == 'true':
            print(f"🔍 {decision.upper()}: {selector} ({element_info}) - {reason}")
    
    @staticmethod  
    def save_debug_screenshots(visualizations: List[VisualizationArea], output_dir: str):
        """Save individual screenshots for debugging."""
        if os.getenv('VISUAL_CAPTURE_DEBUG') == 'true':
            os.makedirs(output_dir, exist_ok=True)
            for i, viz in enumerate(visualizations):
                debug_path = f"{output_dir}/debug_capture_{i}_{viz.element_type}_{viz.slide_index}.png"
                try:
                    with open(debug_path, 'wb') as f:
                        f.write(viz.screenshot_data)
                    print(f"💾 Debug screenshot saved: {debug_path}")
                except Exception as e:
                    print(f"❌ Error saving debug screenshot: {e}")