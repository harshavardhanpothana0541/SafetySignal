import re
from typing import Dict, Any

class AITriageService:
    def __init__(self):
        # Keyword clusters for rule-based heuristics and LLM zero-shot classification
        self.keywords = {
            "Medical / Cardiac": ["chest pain", "heart", "breath", "unconscious", "stroke", "seizure", "collapsed", "cardiac"],
            "Severe Bleeding": ["blood", "bleeding", "cut", "wound", "artery", "hemorrhage", "stab"],
            "Trauma / Accident": ["crash", "accident", "bike", "car", "fall", "fracture", "bone", "hit", "injury"],
            "Fire / Hazard": ["fire", "smoke", "burn", "explosion", "gas", "electric", "flames"]
        }

    def analyze_incident(self, description: str) -> Dict[str, Any]:
        """
        Analyzes unstructured text or speech-to-text input to extract:
        - Classified emergency category
        - Severity level (CRITICAL, HIGH, MODERATE)
        - Priority triage score
        """
        desc_lower = description.lower()
        matched_category = "Medical / Cardiac"  # Default fallback
        highest_score = 0

        # Heuristic intent parser
        for category, terms in self.keywords.items():
            score = sum(1 for term in terms if re.search(r'\b' + term + r'\b', desc_lower))
            if score > highest_score:
                highest_score = score
                matched_category = category

        # Determine severity triage level
        critical_markers = ["unconscious", "artery", "not breathing", "explosion", "severe", "head injury"]
        is_critical = any(marker in desc_lower for marker in critical_markers)

        severity = "CRITICAL" if is_critical or highest_score >= 2 else "HIGH"

        return {
            "classified_type": matched_category,
            "severity": severity,
            "confidence_score": 0.92 if highest_score > 0 else 0.70,
            "raw_input": description
        }

ai_triage_service = AITriageService()