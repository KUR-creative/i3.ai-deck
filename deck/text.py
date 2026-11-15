"""Plain terminal-cell clipping shared by the TUI and notifications."""
import unicodedata


def fit(text, width):
    result, used = [], 0
    for char in str(text):
        if not char.isprintable():
            continue
        size = 0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1)
        if used + size > width:
            break
        result.append(char)
        used += size
    return ''.join(result)
