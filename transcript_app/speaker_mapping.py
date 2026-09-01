"""Maps diarization speaker IDs (e.g. 'Guest-1') to human-friendly participant names."""


class SpeakerMapper:
    def __init__(self, participant_names: list[str] | None = None):
        self._known_names = [n.strip() for n in (participant_names or []) if n.strip()]
        self._id_to_name: dict[str, str] = {}
        self._next_name_index = 0

    def resolve(self, speaker_id: str) -> str:
        """Return the display name for a speaker id, assigning the next known name on first sight."""
        if speaker_id in self._id_to_name:
            return self._id_to_name[speaker_id]

        if self._next_name_index < len(self._known_names):
            name = self._known_names[self._next_name_index]
            self._next_name_index += 1
        else:
            name = speaker_id

        self._id_to_name[speaker_id] = name
        return name

    def rename(self, speaker_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if new_name:
            self._id_to_name[speaker_id] = new_name

    def known_speaker_ids(self) -> list[str]:
        return list(self._id_to_name.keys())

    def mapping(self) -> dict[str, str]:
        return dict(self._id_to_name)
