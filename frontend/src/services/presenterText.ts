/**
 * Notes pane text for one slide: the talk track, then a line "Notes:", then the notes.
 *
 * Mirrors the server rule in `slide_notes_text` (src/api/routes/export.py). A present
 * `speaker_notes` string wins even when empty, so a cleared note never returns from an
 * older `notes` key. Each field is trimmed. With one field empty, only the other is returned.
 */
export function presenterPaneText(slide: {
  talk_track?: string;
  speaker_notes?: string;
  notes?: string;
}): string {
  const notes = (
    typeof slide.speaker_notes === 'string' ? slide.speaker_notes : slide.notes || ''
  ).trim();
  const talk = (typeof slide.talk_track === 'string' ? slide.talk_track : '').trim();
  if (talk && notes) return `${talk}\n\nNotes:\n${notes}`;
  return talk || notes;
}
