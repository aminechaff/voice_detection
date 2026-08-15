from __future__ import annotations

from .transcription import Transcript

Dialogue = list[tuple[str, str]]


def merge_live_text(current: str, incoming: str) -> str:
    """Append a transcript chunk while removing its overlapped prefix."""
    old_words = current.split()
    new_words = incoming.strip().split()
    if not new_words:
        return current
    normalized_old = [_normalize(word) for word in old_words]
    normalized_new = [_normalize(word) for word in new_words]
    overlap = 0
    for size in range(min(20, len(old_words), len(new_words)), 0, -1):
        if normalized_old[-size:] == normalized_new[:size]:
            overlap = size
            break
    addition = " ".join(new_words[overlap:])
    return f"{current.rstrip()} {addition}".strip() if current else addition


def interleave_transcripts(transcripts: dict[str, Transcript]) -> Dialogue:
    """Order source segments by timestamp and merge adjacent same-source turns."""
    timed = sorted(
        (
            (segment.start, segment.end, source, segment.text)
            for source, transcript in transcripts.items()
            for segment in transcript.segments
        ),
        key=lambda item: (item[0], item[1]),
    )
    dialogue: Dialogue = []
    for _, _, source, text in timed:
        append_turn(dialogue, source, text)
    return dialogue


def append_deduplicated_turns(
    dialogue: Dialogue,
    accumulated: dict[str, str],
    turns: Dialogue,
) -> None:
    """Append only the new portion of overlapped live-transcription turns."""
    for source, text in turns:
        previous = accumulated.get(source, "")
        merged = merge_live_text(previous, text)
        addition = merged[len(previous) :].strip() if previous else merged
        accumulated[source] = merged
        append_turn(dialogue, source, addition)


def append_turn(dialogue: Dialogue, source: str, text: str) -> None:
    text = text.strip()
    if not text:
        return
    if dialogue and dialogue[-1][0] == source:
        dialogue[-1] = (source, f"{dialogue[-1][1].rstrip()} {text}")
    else:
        dialogue.append((source, text))


def _normalize(word: str) -> str:
    return word.casefold().strip(".,!?;:…")
