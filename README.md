# qsl-send

Generate QSL cards from an ADIF log and a card template image, resolve each
operator's e-mail address, and send the cards out.

The two stages are separate on purpose. `generate` renders one card per QSO and
writes a manifest listing the recipient and file name for every card, so you can
review the whole batch. `send` then mails exactly what the manifest describes —
and previews by default, so nothing leaves until you pass `--confirm`.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

That puts a `qsl-send` command in `.venv/bin`. Without installing, every command
below also works as `.venv/bin/python -m qsl_send …`.

## Quick start

```bash
cp qsl-send.example.yaml qsl-send.yaml     # edit paths and options
qsl-send check                             # validate config, log and template
qsl-send generate                          # render cards + manifest
qsl-send send                              # preview the batch — sends nothing
qsl-send send --confirm                    # deliver
```

Output lands in `output/`:

```
output/
  cards/AA1AA_20260823_1415.jpg   … one per QSO
  manifest.csv                    … recipient + file name per card
  manifest.json                   … the same, plus run totals and warnings
  sent.json                       … written by `send`; who was mailed, when
```

Each run prints a summary: how many cards were written, how many have an
address, and which callsigns are missing one.

## Commands

| Command | What it does |
| --- | --- |
| `qsl-send check` | Validates the config, log and template; prints the field boxes and how many QSOs carry an `<email>` field. Writes nothing. |
| `qsl-send detect-fields` | Finds the template's field boxes automatically and prints them as YAML; `--write` puts them in the config. |
| `qsl-send generate` | Renders the cards and writes the manifest. Sends nothing. |
| `qsl-send send` | E-mails the cards listed in the manifest. Previews by default; `--confirm` delivers. |

Useful `generate` flags:

```
-c/--config FILE     config file (default: ./qsl-send.yaml)
-a/--adif FILE       ADIF log, overrides the config
-t/--template FILE   template image, overrides the config
-o/--output-dir DIR  output directory, overrides the config
--contacts FILE      address-book overrides (see "The contacts file")
--limit N            only the first N QSOs — handy for a quick look
--call AA1AA         only this callsign (repeatable)
--qrz / --no-qrz     force QRZ.com lookups on or off for this run
--refresh-qrz        ignore the QRZ cache and re-query
--manifest-only      resolve recipients without rendering images
-q/--quiet           print only the summary
```

## The template

The bundled `template.jpg` is a generic example card with seven blank boxes
along the bottom — DATE, QSO with, Name, QRG, UTC, Mode and R-S-T. Replace it
with your own design. The config maps each box to a rectangle in template pixels
and a value template:

```yaml
render:
  template_size: [1583, 1061]   # size the boxes below were measured on
  fields:
    - name: name
      box: [463, 951, 291, 42]  # x, y, width, height
      value: "{name_title}"
      max_chars: 28
```

Text is centred in its box and shrunk automatically until it fits, so a long
name like `Fernando de los Santos Ejemplo` stays inside the box. If your
template is a different pixel size, the boxes are scaled proportionally and the
run warns you.

`field.name` is just an identifier shown by `qsl-send check` — name the fields
in whatever language your card is printed in.

Placeholders available in `value`, in the output `filename`, and in the e-mail
subject/body:

```
{date} {date_iso} {callsign} {base_callsign} {name} {name_title} {name_first}
{qrg} {freq} {band} {utc} {utc_raw} {time_off} {mode} {rst} {rst_rcvd}
{qth} {gridsquare} {country} {email} {my_callsign} {my_name} {my_gridsquare}
{my_qth} {tx_pwr} {index}
```

Per-field options: `align`, `valign`, `font`, `color`, `max_font_size`,
`min_font_size`, `padding`, `uppercase`, `fit` (`shrink`/`clip`), `max_chars`.

Three name variants, since logs are inconsistent about capitalisation:

| Placeholder | `ANA DE LOS SANTOS EJEMPLO` gives |
| --- | --- |
| `{name}` | `ANA DE LOS SANTOS EJEMPLO` (verbatim from the log) |
| `{name_title}` | `Ana de los Santos Ejemplo` |
| `{name_first}` | `Ana` — for greetings like `Hola {name_first}!` |

`{name_first}` falls back to the callsign when the log has no name, so a
greeting never renders as `Hola !`.

### Adjusting a box

Open the template in any image editor, read off the rectangle of the blank box
in pixels, and put those four numbers in `box`. Then re-run
`qsl-send generate --limit 1` and look at the single card produced.

### Finding the boxes automatically

Measuring seven rectangles by hand for every new card gets old. `detect-fields`
finds them for you:

```bash
qsl-send detect-fields QSL_CARD.jpg --preview check.jpg   # look first
qsl-send detect-fields QSL_CARD.jpg --write               # write into the config
```

It scans the lower part of the card for flat rectangles of a single colour —
which is how QSL cards almost always mark write-in areas — and prints a
ready-to-paste YAML block. It is entirely local: no network, no OCR, no image
service. Pillow only.

```
Template : QSL_CARD.jpg (1607x1061)
Fill     : #00AFF0
Rows     : 1    Boxes: 7

  #  row  box                        name
  0  0    [402, 920, 174, 41]        fecha
  1  0    [586, 921, 173, 41]        qso_con
  ...
```

**Names come from reading order, not from the card.** The detector finds
geometry; it cannot know which box is which. It assumes the usual order —
date, callsign, name, QRG, UTC, mode, RST — and says so on every run. Check the
names before using them, and pass `--order a,b,c,...` if your card differs.
Multi-row layouts are handled: boxes are grouped into rows top to bottom, then
read left to right within each row.

Useful flags:

```
--write            replace render.template_size and render.fields in the config
--preview FILE     save the template with detected boxes outlined and numbered
--order a,b,c      field names in reading order
--search-top 0.55  only look below this fraction of the card height
--tolerance 26     colour match tolerance
--colour RRGGBB    force the fill colour instead of detecting it
```

If it finds nothing, the boxes are probably above the default cutoff
(`--search-top 0.3`) or the fill is not flat enough to detect — name it
directly with `--colour`. If it finds too many, some artwork matches the box
colour; raise `--search-top` to exclude it.

`--write` rewrites the `template_size` and `fields` region of the config and
does not preserve hand-written comments in that block. Check the diff.

### Regenerating the example template

`template.jpg` is generated, not hand-drawn. The script imports the default
field boxes from the code, so the image and the config cannot drift apart:

```bash
.venv/bin/python tools/make_example_template.py template.jpg
```

## Where addresses come from

1. **The contacts file**, if configured — a hand-curated address book that
   overrides everything else. See below.
2. The ADIF `<email>` field, which QRZ Logbook exports fill in for most
   contacts. A `<qsl_via>` value is accepted too, but only when it actually
   looks like an address — values like `LoTW - eQSL - Mail` or `Directo` are
   ignored.
3. QRZ.com, when `qrz.enabled` is true, as a fallback. Set `qrz.prefer: qrz` to
   flip the order between the log and QRZ (this does not affect the contacts
   file, which always wins).

The manifest's `email_source` column records which of the three supplied each
address, so nothing is hidden.

### The contacts file

Some operators have no address in the log and none on QRZ. When you track one
down yourself, put it in a YAML address book rather than editing the ADIF —
ADIF fields are length-prefixed and a fresh QRZ export would discard the edit
anyway.

```yaml
# contacts.yaml
AA1AA: someone@example.com
BB2BB:
  email: another@example.com
  name: Name To Print On The Card    # optional; overrides the logged name
```

Point at it with `contacts_file: contacts.yaml` in the config, or
`--contacts FILE` on the command line. Entries are matched on the **base
callsign**, so an entry for `CC3CC` also covers a `CC3CC/A` contact in the log.

Values that clearly are not addresses are ignored with a warning rather than
mailed to.

### QRZ.com

QRZ lookups use the XML data service and need a QRZ **XML subscription** —
without one the service returns no `<email>` element. Lookups are cached in
`.qrz-cache.json`, keyed by base callsign, so re-runs over the same log cost
nothing; `--refresh-qrz` bypasses the cache. If login fails the run continues
with the addresses it already has and records a warning in the summary and
manifest.

### Contacts without an address

Cards are still rendered for them by default (they show up as
`status: no_email` in the manifest) so you can post or hand them out. Set
`skip_without_email: true` to skip those instead.

## Privacy

A QSL run handles other operators' names and e-mail addresses. These paths are
git-ignored by default, and should stay that way:

| Path | Why |
| --- | --- |
| `*.adi` | the log — names and addresses for every contact |
| `contacts.yaml` | your hand-curated address book |
| `output/` | rendered cards carry names; the manifest carries addresses |
| `.qrz-cache.json` | cached QRZ lookups |
| `.env`, `qsl-send.yaml` | credentials and local paths |

If you want to commit a sample log for others to try, write one with
placeholder callsigns and `example.com` addresses, and add an explicit
`!sample.adi` exception to `.gitignore`.

## Credentials

Never put passwords in `qsl-send.yaml` — it is git-ignored, but still. Write
`${VAR}` in the config and keep the value in the environment or in a `.env`
file next to the config:

```
QRZ_USERNAME=…
QRZ_PASSWORD=…
SMTP_USERNAME=…
SMTP_PASSWORD=…
```

## Manifest columns

`callsign`, `name`, `email`, `email_source` (`override`/`adif`/`qrz`/`none`),
`name_source`, `qso_date`, `time_on`, `mode`, `band`, `freq`, `rst_sent`,
`qso_count` (how many times that station appears in the log), `card_file`,
`status` (`ok`/`no_email`/`error`), `notes`.

The CSV is written with a BOM so Excel opens accented names correctly.
`manifest.json` carries the same rows plus the resolved placeholder values,
which is what `send` uses to fill in the subject and body.

## Sending

`send` reads `output/manifest.json` from the last `generate` run, so review the
cards first. It never sends unless you pass `--confirm`:

```bash
qsl-send send --to me@example.com --limit 3            # preview a test batch
qsl-send send --to me@example.com --limit 3 --confirm  # send it to yourself
qsl-send send                                          # preview the real batch
qsl-send send --confirm                                # send it for real
```

`--to ADDRESS` is test mode: every message is redirected to that one address,
the real recipients are never contacted, and **nothing is written to the sent
log** — so a test run does not mark anyone as done. The preview shows each
message's real recipient in brackets so you can confirm the routing.

Flags:

```
--to ADDRESS      redirect the whole batch to one address (test mode)
--confirm         actually deliver; without it, send only previews
--limit N         send at most N messages
--call AA1AA      only this callsign (repeatable)
--resend          ignore the sent log and mail someone again
--delay SECONDS   pause between messages (default: smtp.delay, 2s)
-c/--config FILE  config file (default: ./qsl-send.yaml)
-o/--output-dir   directory holding manifest.json and cards/
```

### Not sending twice

Every real delivery is appended to `output/sent.json`, keyed by callsign + card
file + address. A later `qsl-send send --confirm` skips anyone already in it and
says how many it skipped, so interrupting a batch and re-running it is safe.
`--resend` overrides this.

This also makes late additions easy: find a missing address, add it to
`contacts.yaml`, re-run `generate` and `send --confirm`, and only the new
recipients are mailed.

Delivery failures do not stop the batch: each is reported at the end with its
SMTP error, and only successful sends are recorded — so a re-run retries just
the failures.

### The From display name

`smtp.from_name` is sent as the `From` display name, and Gmail relays it
unchanged — confirmed by inspecting the headers as received.

If a message *appears* to show only the bare address, check the raw headers
before changing anything — the name is usually there. A client may be
overriding it from its own address book: Proton Mail, for one, auto-saves
addresses you have written to and then shows the stored contact name in
preference to the `From` header, so a contact saved without a name renders as
the bare address. Parentheses in the name are fine — a display name like
`Example Operator (MY1CLL)` is quoted correctly and passes through.

The one thing Gmail does enforce is the *address*: it rewrites `From` to the
authenticated account unless the address is a verified "Send mail as" alias.

### Gmail

Host `smtp.gmail.com`, port 587, STARTTLS, and a 16-character
[App Password](https://myaccount.google.com/apppasswords) (2-Step Verification
must be on). Paste it into `.env` as `SMTP_PASSWORD`; the spaces Google shows
are presentational and are stripped automatically. A free Gmail account allows
roughly 500 recipients a day, well above a typical activation's log.

Proton Mail needs a paid plan either way: direct SMTP submission
(`smtp.protonmail.ch:587`) additionally requires a custom-domain address, and
Proton Mail Bridge (`127.0.0.1:1025`) requires the Bridge app to be running
while you send.

## Running the window on macOS or Linux

The window is plain tkinter and works on every desktop platform — it is not
Windows-only. The one requirement is a Python **built with tkinter**, which is
where it usually goes wrong:

| Python | tkinter? |
| --- | --- |
| python.org installer (macOS/Windows) | yes |
| Homebrew `python@3.x` + `brew install python-tk@3.x` | yes |
| macOS system `/usr/bin/python3` | yes, but only 3.9 — too old for this project |
| **pyenv** builds | **usually not**, unless Tk was present when it was built |

Check whichever interpreter you plan to use:

```bash
python3 -c "import tkinter; print(tkinter.TkVersion)"
```

If that fails, the venv you built the project in cannot open the window. Make
one from a Python that has tkinter:

```bash
brew install python-tk@3.13                 # once, if using Homebrew Python
/opt/homebrew/bin/python3.13 -m venv .venv-gui
.venv-gui/bin/pip install -e .
.venv-gui/bin/qsl-send-gui                  # opens the window
```

Or without installing anything:

```bash
.venv-gui/bin/python -m qsl_send.gui
```

Either form accepts a config path — `qsl-send-gui path/to/qsl-send.yaml` —
otherwise it looks for `qsl-send.yaml` in the current folder and pre-fills the
boxes from it.

The command line is unaffected and keeps working in your normal venv; only the
window needs tkinter.

## For Windows users (no Python needed)

Colleagues who are not developers should not have to install Python, use a
terminal, or edit YAML. For them, the app is packaged as a Windows installer
with a small window.

### The window

Double-clicking **QSL Sender** opens a window that walks through the job in the
order it is actually done:

```
1. Files        card design · log file · where to save
2. Card layout  [Find fields automatically]  [Show me…]
3. Make/send    [Make the cards] [Review who gets one…]
                [Send a test to myself]      [Send the e-mails]
```

The same safety rules as the command line apply, and they are enforced by the
interface rather than by remembering a flag:

- **Sending is never one click from opening the app.** You must make the cards,
  and the Send button stays disabled until you have.
- **Confirmation names the number.** "This will e-mail 23 operator(s) — for
  real", defaulting to No.
- **"Send a test to myself"** delivers one card to an address you type, and
  never marks anyone as having received theirs.
- **"Review who gets one…"** opens `manifest.csv` in Excel before anything is
  sent.
- Long jobs run on a background thread, so the window never freezes.

Running the packaged app with arguments still gives the full command line, so
nothing is lost for people who prefer it.

### Building it

Two supported routes; both produce the same thing.

**On a Windows PC**, from the project root:

```bat
packaging\build-windows.bat
```

That creates `dist\QSL Sender\`. To produce the installer as well, install
[Inno Setup](https://jrsoftware.org/isdl.php) and run `iscc packaging\installer.iss`.

**Or let GitHub build it.** `.github/workflows/build-windows.yml` runs the tests,
builds the app and compiles the installer on a Windows runner. Trigger it by
hand from the Actions tab, or push a version tag:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Tagged builds attach `QSL-Sender-Setup-0.1.0.exe` to a GitHub Release, so
colleagues get a download link rather than a zip by e-mail.

### Notes on the packaging choices

- **One-folder, not one-file.** A single .exe unpacks itself to a temp folder
  on every launch, which is slow and is flagged by SmartScreen and antivirus far
  more often. The installer hides the folder from users anyway.
- **Per-user install** (`PrivilegesRequired=lowest`), so no administrator rights
  are needed — which matters on a locked-down work machine.
- **No console window** (`console=False`), so double-clicking does not show a
  black terminal.
- **Unsigned.** Windows will show a SmartScreen warning on first run; the user
  clicks "More info" then "Run anyway". Removing that warning requires a paid
  code-signing certificate.

### Settings for colleagues

Each person still needs their own `qsl-send.yaml` beside the app, with their own
callsign and their own Gmail App Password in `.env`. Never share a password
between people — send each colleague the example files and let them fill in
their own.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

Fixtures use placeholder callsigns and `example.com` addresses throughout — no
data from a real log. The detector tests draw their own synthetic cards rather
than reading the real templates, which are git-ignored.

## Not done yet

- No HTML alternative part — messages are plain text with the card attached.
- The card is attached, not embedded inline in the message body.
- No bounce handling: a message the SMTP server accepts but the far end later
  rejects is still recorded as sent.
