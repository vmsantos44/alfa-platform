"""Helper utility functions for the Alfa Platform."""

import re


def clean_candidate_label(label: str) -> str:
    """
    Remove prefixes like 'No-show:', 'no show', 'New Candidate:', 'new task'
    and return the candidate's name in Title Case.
    """
    if not label:
        return ""
    
    # Patterns to remove (order matters - more specific first)
    prefixes = [
        r'^No-show:\s*',
        r'^No-show\s+',
        r'^no-show:\s*',
        r'^no-show\s+',
        r'^no show:\s*',
        r'^no show\s+',
        r'^New Candidate:\s*',
        r'^New Candidate\s+',
        r'^new task:\s*',
        r'^new task\s+',
    ]
    
    # Suffixes to remove
    suffixes = [
        r',?\s*Please follow [Uu]p\s*$',
    ]
    
    cleaned = label.strip()
    
    for pattern in prefixes:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    for pattern in suffixes:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Convert to Title Case
    return cleaned.strip().title()
