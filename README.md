# Transcriere întâlniri în timp real (aplicație locală)

Aplicație Python care rulează **local, pe computerul tău**, capturează audio de la microfon și produce
**transcript în timp real, cu identificarea vorbitorilor (diarization)**, folosind serviciul de
transcriere Azure AI Speech, disponibil prin **Microsoft Azure AI Foundry**. La final, conversația este
salvată pe disc (JSON + text), împreună cu numele participanților.

Poate fi folosită atât pentru **întâlniri fizice** (microfonul laptopului), cât și pentru
**apeluri Microsoft Teams** (setând ca sursă de intrare implicită a sistemului un dispozitiv de
tip loopback/virtual audio cable — vezi secțiunea [Capturarea unui apel Teams](#capturarea-unui-apel-teams)).

---

## De ce Azure AI Speech (Azure AI Foundry)?

Modelul de transcriere Azure AI Speech oferă:
- **Transcriere în timp real** direct din stream-ul de microfon (nu e nevoie de înregistrare + procesare offline).
- **Diarization nativ** (`ConversationTranscriber`): fiecare frază este atribuită automat unui vorbitor
  (`Guest-1`, `Guest-2`, ...), fără modele/pipeline-uri suplimentare.
- Acces printr-o resursă Azure AI Foundry / Azure AI services, cu suport pentru multe limbi (inclusiv română).

---

## Cerințe

- Python 3.11+
- Un microfon funcțional
- O resursă **Speech** creată în [Azure AI Foundry](https://ai.azure.com) (sau Azure AI services din portalul Azure)
  cu o cheie și o regiune (sau un endpoint dedicat)

---

## Instalare locală

1. **Clonează repository-ul:**
    ```bash
    git clone https://github.com/ariqbasyar/speech-to-text-whisper.git
    cd speech-to-text-whisper
    ```

2. **Creează și activează un mediu virtual:**
    ```bash
    python -m venv env
    source env/bin/activate  # Pe Windows: env\Scripts\activate
    ```

3. **Instalează dependențele:**
    ```bash
    pip install -r requirements.txt
    ```

4. **Configurează credențialele Azure AI Foundry Speech:**
    - Copiază `.env.example` în `.env`:
      ```bash
      cp .env.example .env
      ```
    - Completează `.env` cu cheia și regiunea resursei tale Speech:
      ```
      AZURE_SPEECH_KEY=cheia-ta
      AZURE_SPEECH_REGION=westeurope
      AZURE_SPEECH_LANGUAGE=ro-RO
      ```

---

## Utilizare

1. **Pornește aplicația:**
    ```bash
    python main.py
    ```
2. Se deschide o fereastră locală (GUI):
   - Introdu numele participanților în câmpul **"Participanți"**, separate prin virgulă, în ordinea
     probabilă în care vor vorbi prima dată (ex: `Ana, Bogdan, Cristina`). Pe măsură ce apar vorbitori noi,
     aplicația le atribuie automat următorul nume din listă.
   - Apasă **▶ Pornește** pentru a începe transcrierea live.
   - Transcriptul apare în timp real, cu numele vorbitorului și ora fiecărei fraze; textul gri este
     previzualizarea frazei curente (încă neconfirmată).
   - Dacă un vorbitor a fost etichetat greșit, folosește panoul **"Redenumește vorbitor"** pentru a
     corecta numele — corecția se aplică imediat, inclusiv retroactiv în transcript.
   - Apasă **■ Oprește și salvează** la final. Conversația este salvată automat în folderul `transcripts/`,
     ca fișier `.json` (structurat, cu mapping-ul vorbitorilor) și `.txt` (lizibil).

---

## Capturarea unui apel Teams

Aplicația transcrie orice sunet primit prin **microfonul implicit al sistemului**. Pentru a transcrie
un apel Teams (vocea celorlalți participanți, nu doar microfonul tău), trebuie ca sunetul de ieșire al
apelului să ajungă pe un dispozitiv de intrare:

- **Windows:** activează "Stereo Mix" din Sound Settings sau instalează un cablu audio virtual
  (ex. [VB-CABLE](https://vb-audio.com/Cable/)) și setează-l ca dispozitiv de redare implicit pentru Teams
  și ca microfon implicit pentru această aplicație.
- **macOS:** instalează [BlackHole](https://github.com/ExistentialAudio/BlackHole) sau Loopback și
  creează un dispozitiv agregat (microfon + BlackHole), setat ca intrare implicită.
- **Linux:** creează un sink virtual PulseAudio/PipeWire (`pactl load-module module-null-sink ...`) și
  setează-l ca sursă implicită de înregistrare.

> Verifică politica organizației / consimțământul participanților înainte de a înregistra o întâlnire.

---

## Structura proiectului

```
main.py                        # punct de intrare, pornește GUI-ul
transcript_app/
  config.py                    # citește credențialele Azure din .env
  transcriber.py                # wrapper peste Azure ConversationTranscriber (streaming + diarization)
  speaker_mapping.py            # asociază etichetele de vorbitor (Guest-1...) cu nume reale
  session_store.py              # salvează transcriptul (JSON + txt) la final
  gui.py                        # interfața grafică (Tkinter): pornire/oprire, live view, redenumire
transcripts/                    # transcripturile salvate (ignorate din git)
```

---

## Confidențialitate

Audio-ul este trimis către serviciul Azure AI Speech pentru procesare, conform politicilor Microsoft
pentru resursa configurată. Fișierele `.env` (cu cheile tale) și `transcripts/` (conversațiile salvate)
sunt excluse din git prin `.gitignore`.

---

## Licență

MIT

