# 20 · DirectMusic and DirectSound

This guide tells you how to find, name and reconstruct the audio code of
a game of the DirectX 5 to 9 period. It covers two components:

- **DirectSound** plays PCM buffers. It mixes them and positions them
  in 3D.
- **DirectMusic** plays music. It reads segments, styles, bands and DLS
  instrument banks, and renders them through its own software synth.

It also tells you what breaks in this code on modern systems, and how
to fix it in a modern build.

The rule that this guide teaches first:

> **Silence is not evidence.** An audio fault seldom crashes. Record
> the audio stream, count the calls, and compare both with the retail
> binary. Do not decide by ear.

The examples are from the LithTech games of our projects. For the
general method of a modern build, see
[18 · Building a modern variant](18_modern_builds.md). This guide does
not repeat it.

## 1. Find the audio layer first

Many games put a layer between the game and DirectSound. The layer can be
third-party middleware (for example Miles) or the engine's own sound
driver. Find the layer first, because the layer decides what you
reconstruct and what you replace.

Example: the layers in our projects.

| Game | Music | Sound effects and speech |
|---|---|---|
| NOLF, AvP2 | DirectMusic, `IDirectMusicPerformance2` | Miles 6.0i (`mss32.dll`) |
| NOLF 2, Contract J.A.C.K., Tron 2.0 | DirectMusic, `IDirectMusicPerformance8` | the engine's own `SndDrv.dll` on DirectSound 8 |

We read the interface IDs from the retail images. The `SndDrv.dll` of
the later games is engine code. Thus, we reconstruct it (nolf2src
71ae904, cjacksrc 463917f). Miles is third-party code. Thus, we replace
it with OpenMiles, a clean-room implementation (nolfsrc 09e8969, avp2src
0972582).

## 2. Recognise the components in a binary

### Imports

| DLL | Entry points | What they tell you |
|---|---|---|
| `DSOUND.dll` | `DirectSoundCreate`, `DirectSoundCreate8`, `DirectSoundEnumerateA` | DirectSound, created by a direct call |
| `ole32.dll` | `CoInitialize`, `CoCreateInstance`, `CoUninitialize` | COM objects, possibly DirectMusic or DirectSound |
| `MSACM32.dll` | `acmStreamOpen`, `acmStreamConvert`, `acmDriverEnum`, `acmFormatSuggest` | compressed audio decoded by the system codecs |
| `mss32.dll` | `AIL_startup`, `AIL_open_digital_driver`, ... | Miles Sound System |

DirectMusic has no entry point to import. A game makes every
DirectMusic object with `CoCreateInstance` and a CLSID. DirectSound can
also come from COM. Example: the retail `SndDrv.dll` of NOLF 2, Contract
J.A.C.K. and Tron 2.0 does not import `DSOUND.dll`. It calls
`CoCreateInstance(CLSID_DirectSound8, ..., IID_IDirectSound8)` and then
`IDirectSound8::Initialize(NULL)` (nolf2src `src/Engine/snddrv/s_dx8.cpp`,
`CDx8SoundSys::Init`).

Thus, if a binary imports `CoCreateInstance` and no audio DLL, search
`.rdata` for the audio CLSIDs.

A sound driver DLL that the engine loads by name has no import in the
engine either. Example: the engine of NOLF 2 calls `LoadLibrary` on a
sound driver name, then `GetProcAddress(h, "SoundSysMake")`. The default
name is `snddrv.dll` (nolf2src `src/Engine/runtime/sound/src/iltsound.cpp`).
Search for the export names as strings. The vtable of the object that
`SoundSysMake` returns is the contract of the driver. Its method names
follow Miles (`WaveOutOpen`, `LHDIGDRIVER`, `S32`).

### GUIDs in `.rdata`

The GUIDs come from `dxguid.lib` or from a header with `INITGUID`. Name
each one from its bytes in the SDK header, not from the name that a
decompiler or an older note gives. These GUIDs are the usual anchors:

| Name | Value |
|---|---|
| `CLSID_DirectMusicPerformance` | `{D2AC2881-B39B-11D1-8704-00600893B1BD}` |
| `CLSID_DirectMusicLoader` | `{D2AC2892-B39B-11D1-8704-00600893B1BD}` |
| `CLSID_DirectMusicCollection` | `{480FF4B0-28B2-11D1-BEF7-00C04FBF8FEF}` |
| `GUID_NOTIFICATION_SEGMENT` | `{D2AC2899-B39B-11D1-8704-00600893B1BD}` |
| `IID_IDirectMusicPerformance` | `{07D43D03-6523-11D2-871D-00600893B1BD}` |
| `IID_IDirectMusicPerformance2` | `{6FC2CAE0-BC78-11D2-AFA6-00AA0024D8B6}` |
| `IID_IDirectMusicPerformance8` | `{679C4137-C62E-4147-B2B4-9D569ACB254C}` |
| `IID_IDirectMusicLoader` | `{2FFAACA2-5DCA-11D2-AFA6-00AA0024D8B6}` |
| `IID_IDirectMusicLoader8` | `{19E7C08C-0A44-4E6A-A116-595A7CD5DE8C}` |
| `CLSID_DirectSound8` | `{3901CC3F-84B5-4FA4-BA35-AA8172B8A09B}` |
| `IID_IDirectSound8` | `{C50A7E93-F395-4834-9EF6-7FA99DE50966}` |
| `IID_IDirectSoundBuffer8` | `{6825A449-7524-4D82-920F-50E36AB3AB1E}` |
| `IID_IDirectSound3DListener` | `{279AFA84-4981-11CE-A521-0020AF0BE560}` |
| `IID_IDirectSound3DBuffer` | `{279AFA86-4981-11CE-A521-0020AF0BE560}` |

To find them, search the image for the 16 bytes of each GUID in
little-endian field order (`uuid.UUID(s).bytes_le` in Python).

NOTE: If your tools mask relocations, a wrong GUID name still gives a
byte-identical match. Only the address of the push is compared. Thus,
check each GUID name against the bytes one time, and write the address
beside the declaration.

### Which SDK version

Use three facts together:

1. **The interface IDs.** The NOLF and AvP2 engines ask for
   `IID_IDirectMusicPerformance2` and `IID_IDirectMusicLoader`, the
   DirectX 6.1 and 7 interfaces. The NOLF 2, Contract J.A.C.K. and Tron
   2.0 engines ask for the `8` interfaces.
2. **The `dwSize` values.** A structure that grew between versions shows
   the header that compiled it. Example: `DMUS_PORTPARAMS7` is 0x20
   bytes and `DMUS_PORTPARAMS8` is 0x24 bytes. The NOLF engine gives
   0x24 (nolfsrc `clientmusic.h`), but asks for
   `IID_IDirectMusicPerformance2`. Thus, DirectX 8 headers compiled it.
3. **The flag values.** Decode each flag with the header of that
   version. Example: `DMUS_SEGF_QUEUE` is 0x100. `DMUS_SEGF_SEGMENTEND`
   is 0x800000 and is new in DirectX 8. An engine that queues "at the
   end of the segment" with 0x100 uses the queue flag.

## 3. COM calls in the disassembly

### The call shape

Every DirectSound and DirectMusic method is `__stdcall`. The object
pointer is the first stack argument, not `ecx`. Visual C++ 6 compiles
`pBuffer->Play(0, 0, DSBPLAY_LOOPING)` to this shape:

```asm
mov   eax, [esi+0x08]       ; the IDirectSoundBuffer* member
push  1                     ; dwFlags = DSBPLAY_LOOPING
push  0                     ; dwPriority
push  0                     ; dwReserved1
mov   ecx, [eax]            ; the vtable
push  eax                   ; this
call  dword ptr [ecx+0x30]  ; slot 0x30 = Play
```

The C macros of the SDK (`IDirectSoundBuffer_Play(p, a, b, c)`) compile
to the same bytes as the C++ call. For the method of naming slots from
vtables, see [07 · Naming anonymous functions from vtables](07_vtables.md).

### Slot offsets

All offsets count from the start of the vtable. Slots 0x00, 0x04 and
0x08 are `QueryInterface`, `AddRef` and `Release`.

| Interface | Slots |
|---|---|
| `IDirectSound` / `8` | 0x0c CreateSoundBuffer, 0x10 GetCaps, 0x14 DuplicateSoundBuffer, 0x18 SetCooperativeLevel, 0x1c Compact, 0x20 GetSpeakerConfig, 0x24 SetSpeakerConfig, 0x28 Initialize, 0x2c VerifyCertification (`8` only) |
| `IDirectSoundBuffer` / `8` | 0x0c GetCaps, 0x10 GetCurrentPosition, 0x14 GetFormat, 0x18 GetVolume, 0x1c GetPan, 0x20 GetFrequency, 0x24 GetStatus, 0x28 Initialize, 0x2c Lock, 0x30 Play, 0x34 SetCurrentPosition, 0x38 SetFormat, 0x3c SetVolume, 0x40 SetPan, 0x44 SetFrequency, 0x48 Stop, 0x4c Unlock, 0x50 Restore; `8` only: 0x54 SetFX, 0x58 AcquireResources, 0x5c GetObjectInPath |
| `IDirectSound3DBuffer` | 0x0c GetAllParameters ... 0x30 SetAllParameters, 0x40 SetMaxDistance, 0x44 SetMinDistance, 0x48 SetMode, 0x4c SetPosition, 0x50 SetVelocity |
| `IDirectSound3DListener` | 0x0c GetAllParameters ... 0x28 SetAllParameters, 0x2c SetDistanceFactor, 0x30 SetDopplerFactor, 0x34 SetOrientation, 0x38 SetPosition, 0x3c SetRolloffFactor, 0x40 SetVelocity, 0x44 CommitDeferredSettings |
| `IDirectMusic` / `8` | 0x0c EnumPort, 0x14 CreatePort, 0x24 Activate, 0x28 GetDefaultPort, 0x2c SetDirectSound |
| `IDirectMusicPerformance` / `2` / `8` | 0x0c Init, 0x10 PlaySegment, 0x14 Stop, 0x38 IsPlaying, 0x44 FreePMsg, 0x50 SetNotificationHandle, 0x54 GetNotificationPMsg, 0x58 AddNotificationType, 0x60 AddPort, 0x64 RemovePort, 0x68 AssignPChannelBlock, 0x88 SetGlobalParam, 0x98 CloseDown; `8` only: 0xb0 InitAudio, 0xb4 PlaySegmentEx, 0xb8 StopEx |
| `IDirectMusicLoader` / `8` | 0x0c GetObject, 0x10 SetObject, 0x14 SetSearchDirectory, 0x18 ScanDirectory, 0x1c CacheObject, 0x20 ReleaseObject, 0x24 ClearCache, 0x28 EnableCache, 0x2c EnumObject; `8` only: 0x30 CollectGarbage, 0x34 ReleaseObjectByUnknown, 0x38 LoadObjectFromFile |
| `IDirectMusicSegmentState` | 0x0c GetRepeats, 0x10 GetSegment, 0x14 GetStartTime |
| `IDirectMusicStyle` | 0x0c GetBand, 0x14 GetDefaultBand, 0x1c GetMotif |
| `IDirectMusicBand` | 0x0c CreateSegment, 0x10 Download, 0x14 Unload |

We counted these from the DirectX 9 SDK headers. The NOLF engine
confirms many of them independently (nolfsrc `clientmusic.h`,
`dmextra.cpp`).

To anchor a slot, do not trust one call. Find two independent facts.
Example: in NOLF, slot 0x0c of the performance gets
`(&m_pDirectMusic, 0, 0)`, which is `Init`. The header order then puts
`CloseDown` at 0x98, and the code calls slot 0x98 just before `Release`
(nolfsrc `dmextra.cpp` header comment).

### HRESULTs

DirectSound and DirectMusic errors both use facility 0x878. Thus, an
error code has the form 0x8878xxxx. Example: `DMUS_E_LOADER_NOFILENAME`
is 0x88781186. Name each code from `dmerror.h` or `dsound.h`.

Look at how the code tests the result. `test eax, eax` / `jl` is
`FAILED(hr)`. `cmp eax, 0` / `jne` is `hr != S_OK` (`DS_OK`). These
compile differently, so reconstruct the test that the bytes show.

### COM objects that the game implements

A game can implement a DirectMusic interface itself. Then the vtable is
in the game image, and DirectMusic calls into the game.

Recognise such a vtable by these facts:

1. The `ret N` of each slot matches the argument bytes of the interface,
   in header order.
2. A shared `QueryInterface` compares the `riid` with the IIDs of the
   interface (`memcmp` against `.rdata` GUIDs).
3. A second interface of the same object returns `this + 4`.

Example: the NOLF engine does not create `CLSID_DirectMusicLoader`. It
allocates its own loader with a 12-slot `IDirectMusicLoader` vtable.
It also has two `IStream` objects with 14 slots, and each one carries
`IDirectMusicGetLoader` at `+4` (nolfsrc `src/engine/lithtech/dmloader.cpp`).
DirectMusic thus reads every segment and DLS bank through the game's
archive reader, not through the file system.

## 4. How a music system uses DirectMusic

### Startup

The usual order of a DirectX 7 style startup is:

1. `CoInitialize(NULL)`.
2. `CoCreateInstance(CLSID_DirectMusicPerformance, ...)`.
3. Make the loader. This is `CoCreateInstance(CLSID_DirectMusicLoader)`,
   or `new` for a loader of the game.
4. `IDirectMusicPerformance::Init(&pDirectMusic, pDS, hWnd)`. If
   `pDS` is `NULL`, DirectMusic makes its own DirectSound.
5. `IDirectMusic::CreatePort` with `DMUS_PORTPARAMS` and `GUID_NULL`
   (the default synth). Then `Activate(TRUE)`, `AddPort`, and
   `AssignPChannelBlock`.
6. `AddNotificationType(GUID_NOTIFICATION_SEGMENT)`, then
   `SetNotificationHandle(hEvent, 0)`.
7. Start a thread that waits on the event.

Example: the NOLF and AvP2 engines use this sequence. They call
`SetDirectSound(NULL, NULL)` and thus let DirectMusic make its own
DirectSound (nolfsrc `dmextra.cpp`, `InitDirectMusicQ440` and `Init`;
avp2src M-X4).

A DirectX 8 game can use audio paths in place of steps 4 and 5:
`InitAudio` (slot 0xb0), `CreateStandardAudioPath` (0xc4) and
`SetDefaultAudioPath` (0xc8). Example: the NOLF 2 engine makes a
`DMUS_APATH_DYNAMIC_STEREO` path. It gives `InitAudio` the DirectSound
of its own sound driver when the driver has one (nolf2src
`ltdirectmusic_impl.cpp`).

Reverb on the synth port goes through `IKsControl::KsProperty`, with
`GUID_DMUS_PROP_Effects` and `GUID_DMUS_PROP_WavesReverb`. Find it as a
`QueryInterface` of the port for `IID_IKsControl`.

### The loader and its search directory

`IDirectMusicLoader::GetObject` takes a `DMUS_OBJECTDESC`: a class GUID
and a file name, or a memory block. The loader finds the file in the
search directory of that class. A call to `SetSearchDirectory` with
`GUID_DirectMusicAllTypes` sets it for all classes.

A loader of the game does the same work in its own code:

1. Open the file through the game's file system.
2. `CoCreateInstance` the class in the descriptor.
3. `QueryInterface` the new object for `IPersistStream`.
4. Call `IPersistStream::Load` (slot 0x14) with the game's `IStream`.

When DirectMusic loads a segment, it asks the loader again for each
style, band and DLS collection that the segment references. Thus, a
missing file can be a missing search directory. Log each `GetObject`
name and result before you look further.

### Content formats

All DirectMusic content is RIFF. Read the form type at byte 8:

| Extension | RIFF form | Content |
|---|---|---|
| `.sgt` | `DMSG` | a segment: tracks of notes, bands, tempo, references to styles |
| `.sty` | `DMST` | a style: patterns, bands and motifs |
| `.dls` | `DLS ` | a Downloadable Sounds instrument collection (wave pool and instruments) |

The engine usually adds a text control file for each theme. Example:
the LithTech control file gives the synth (`PCHANNELS`, `VOICES`,
`SYNTHSAMPLERATE`), the reverb, the `DLSBANK`, `STYLE` and `BAND` lines,
one `INTENSITY` line per level of tension, and a `TRANSITION` matrix
(nolfsrc `clientmusic.cpp`, `InitLevel`; `dmextra.cpp`).

### The music manager's state machine

A game that changes music with the action usually has these parts:

- **Intensities.** Each intensity is a list of segments that play in
  turn as the primary segment.
- **Transitions.** A table, indexed by the old and the new intensity,
  gives a transition segment and a boundary (`BEAT`, `MEASURE`, ...).
- **A pending queue.** Commands wait in the queue until the current
  segment is almost at its end.
- **Secondary segments and motifs.** They play over the primary
  segment, each with its own segment state.

The notification thread drives the queue:

1. Wait on the event, with a timeout.
2. Get each message with `GetNotificationPMsg` until it fails.
3. On `DMUS_NOTIFICATION_SEGALMOSTEND` (2), take the next pending node.
   Play its segment with `DMUS_SEGF_QUEUE`, or change the intensity.
4. On `DMUS_NOTIFICATION_SEGEND` (1), find the secondary segment or
   motif with that segment state, and remove it.
5. Free each message with `FreePMsg`, on every path.

Example: nolfsrc `clientmusic.cpp`, `dm_NotificationThread`. The NOLF 2
engine has the same design in `ltdirectmusic_impl.cpp`.

NOTE: The notification thread is a new thread that calls COM methods.
Retail NOLF 2 does not call `CoInitialize` on it. The related source
release does, and the nolf2src modern build keeps that form (nolf2src
M-E66).

## 5. How a game uses DirectSound

A DirectSound driver does these steps:

1. Make the device, then call `SetCooperativeLevel(hWnd, DSSCL_PRIORITY)`.
   The priority level is necessary to set the format of the primary
   buffer.
2. Make the primary buffer with `DSBCAPS_PRIMARYBUFFER`. Call
   `SetFormat` on it with the output format, for example 22 kHz or
   44.1 kHz, 16-bit, stereo.
3. `QueryInterface` the primary buffer for `IDirectSound3DListener`.
4. Make one secondary buffer for each sound. Use `DSBCAPS_CTRL3D` for a
   positioned sound, and get its `IDirectSound3DBuffer`.
5. For a long sound, make a streaming buffer. Fill it from a thread with
   `Lock` and `Unlock`.
6. Decode compressed formats (IMA ADPCM, MP3) to PCM before the buffer.
   Old drivers use ACM for this.

EAX goes through `IKsPropertySet` on a buffer, with the
`DSPROPSETID_EAX_*` property sets. Thus, EAX code shows a
`QueryInterface` for `IID_IKsPropertySet` and calls to `QuerySupport`
and `Set`.

## 6. Reconstruction faults that only sound shows

A reconstructed audio function can be byte-identical and still wrong in
the link. These faults are silent. Look for them on purpose.

- **A vtable slot bound to the base class.** In NOLF, the 3D and ambient
  sound instances had the base `Init` in slot 1. That `Init` does not
  copy the position and radii. Thus, every positioned sound was out of
  range and got no voice. A trace of T01S01 started 6 sounds, and retail
  started 31 (nolfsrc 4db6cda). `vtabcheck.py` marked the slot as
  SUSPECT. The same fault was in AvP2 (avp2src 19ee00d).
- **A wrong alias.** In AvP2, `SetSampleUserData` was bound to
  `SetStreamUserData`. Each sample's data went to the stream function
  (avp2src 19ee00d).
- **A wrong string literal.** The retail stream name was four
  backslashes and `%d`. With two, Miles refused it, and the build
  opened the stream again in each frame (avp2src 19ee00d).

To find such faults, do these steps:

1. Trace the audio API with Wine (`WINEDEBUG=+relay` or `+snoop`) for
   one scripted run. For scripted runs, see
   [05 · Reconstructing executables and engine binaries](05_exe_and_engine.md).
2. Count the calls of each kind: samples started, pan updates, streams
   opened.
3. Run the same script with the retail executable and your DLLs, then
   with your executable and the retail DLLs. This finds the faulty
   binary.

Example: avp2src 19ee00d counted 61 samples and 61 pan updates against
201 and 1064 for retail. After the fix, the counts were 215 and 1173.

## 7. What breaks today

### 7.1 Wine and Proton play no music

- **Symptom.** The sound effects play. The music is silent. The game
  shows no error.
- **Cause.** The DirectMusic of Wine, and thus of Proton, is
  incomplete. With Wine 9.0, the AvP2 music loads but plays silence
  (avp2src M-X4). A `dmime.dll` in the game directory does not help,
  because Wine loads its builtin of that name (nolfsrc 0a57051).
- **Fix.** Carry the DirectMusic of Microsoft in the game directory,
  with registration-free COM. Do the steps below.

1. Copy the nine DLLs of the DirectX 9.0c runtime: `dmband`, `dmcompos`,
   `dmime`, `dmloader`, `dmscript`, `dmstyle`, `dmsynth`, `dmusic`,
   `dswave`. Check them against a checksum list.
2. Rename each one to `ms_<name>.dll`. Wine has no builtin of that
   name, so it loads the file. None of the nine imports another by name.
3. Write `<game>.exe.manifest` beside the executable. Give one `<file>`
   element for each DLL, and one `<comClass>` for each class that the
   DLL registers. Then each `CoCreateInstance` finds the DLL without the
   registry. This includes the calls that the DLLs make to each other.
4. List only the classes that the DLLs really contain. Read them from
   the registry after `regsvr32` in a scratch prefix. Our first manifest
   listed two classes that no DLL has (nolfsrc e9755a0). The correct
   list has 46 classes.
5. Do not copy `dsound.dll`. Keep the DirectSound of the system.
6. Copy `gm.dls` only if the game asks for the default GM collection.
   A loader of the game that never gives DirectMusic that collection
   does not need it.

CAUTION: If the executable has an embedded manifest, Windows uses it and
ignores the external file. Then put the COM entries into the embedded
manifest.

CAUTION: If a manifest names a missing file, DirectMusic fails also on
Windows. Install the manifest only together with the DLLs.

**Test.** Use a new prefix with nothing installed. Record the audio
output to a file, for example with an ALSA `file` PCM as the default
device (avp2src `build/playtest.sh`, `PLAYTEST_AUDIO`). Measure the peak
and the RMS. Example: AvP2 music forced to intensity 2 gave a peak of
0.14 with this fix, and 0.00005 with the DirectMusic of Wine (avp2src
a255a4b). Also turn on the game's music log, for example
`+LTDMConsoleOutput 5`, to see which segments load.

The shared installer is `retailextract.py openruntime`, for a layout
that sets `DIRECTMUSIC_MANIFESTS` (tools 314d71c).

CAUTION: The winetricks `directmusic` verb also replaces the DirectSound
of Wine, and the sound effects then repeat. If a user installs
DirectMusic into a prefix, give the DirectMusic verbs one by one
(nolfsrc 5ed85ec).

### 7.2 MP3 speech through ACM plays as a drone

- **Symptom.** Under Wine, streamed speech plays as a drone of its
  first samples. With no MP3 codec, the sound driver does not start.
- **Cause.** The driver decodes MP3 (`WAVE_FORMAT_MPEGLAYER3`, 0x55)
  through ACM, thus with the codec of the system. The MP3 codec of
  Wine, `winemp3.acm`, fails on the streamed decode.
- **Fix.** Decode MP3 in the driver. Replace each `acmStream*` path for
  format 0x55, whole and streamed. Give the same PCM that the retail
  code asked ACM for. Example: cjacksrc compiles minimp3, a single
  header, into `s_dx8.cpp` with the original compiler (cjacksrc EN-50).
- **Test.** Decode every file outside the game, whole and streamed,
  with random read sizes. The two results must be the same bytes.
  cjacksrc did this for 661 voice files.

For the legacy build, install the Fraunhofer codec with
`winetricks l3codecx` (cjacksrc APPS-50, 6ffbb72, 03998c2).

### 7.3 No sound driver crashes the engine

- **Symptom.** A machine with no working sound driver crashes at
  startup. It must run silent.
- **Cause.** In NOLF 2 and Contract J.A.C.K., when no driver can be
  made, `SoundSys` tests the pointer for null and then calls `Term`
  through it.
- **Fix.** Remove the call through the null pointer (nolf2src M-E64,
  cjacksrc EN-7).
- **Test.** Rename the driver DLL and start the game.

### 7.4 Errors that come from data, not from the device

- **Symptom.** The console shows `Couldn't play sound ''` or
  `Couldn't play sound 'x'` when some NOLF levels start (nolfsrc issue
  #64).
- **Cause.** These are not device errors. Level objects play an empty
  sound property. The sound table uses `"x"` as "no sound".
- **Fix.** Treat an empty name and the placeholder as "no sound", with
  no error. Keep the error for a name that is not found (nolfsrc
  M-P5-22).
- **Test.** Start a level that gave the errors (M07S01), and count them.

NOTE: Before you look for a device fault, examine the name that the
error prints.

### 7.5 Music that changes with the frame rate

Above 100 frames a second, the combat music can stop at once. The game
takes one frame of time off each mood in each frame, but the AI adds
time back only at its own update rate. Keep the mood up for the time
that the AI update covers (nolf2src M-G30, cjacksrc GAME-40). See also
[18 · Building a modern variant](18_modern_builds.md#4-frame-rate).

### 7.6 Retail bugs in music managers

Look for these bugs in any music manager. They hang or crash only on
rare paths, thus they survive testing:

- **A stop loop that can find the same node again.** `StopSecondary` and
  `StopMotif` by name test a different member than the stop-all walk.
  A node that is not removed is found again: the game hangs (nolfsrc
  e7f5442; nolf2src M-E7).
- **An untested segment state.** `PlaySegment` can fail and leave the
  segment state `NULL`. The code then calls `QueryInterface` on it
  (cjacksrc EN-5).
- **A table index that is not checked.** The transition table has
  `(I+1)*(I+1)+1` entries. The code checks each intensity but not the
  index (cjacksrc EN-60).
- **A notification that is not freed.** A `continue` skips `FreePMsg`
  (avp2src 4dea255).
- **A thread handle that is not closed** in `Term` (cjacksrc EN-4).
- **A path that leaks** when the control file does not open (nolfsrc
  ebc472b).

### 7.7 Middleware replacements and the attributes they skip

A replacement library must write each output that the game reads. The
retail library can hide a retail bug.

Example: the AvP2 engine reads the "Maximum supported samples" attribute
of the 3D provider into an uninitialised local. Miles always writes it.
An older OpenMiles did not, and the voice count was random. Fix both
sides: start the local at zero (avp2src M-B109), and write the attribute
in the replacement (avp2src M-X7).

Also measure the replacement against the original: volume and pan
curves, resampling, clipping, and the decode format (nolfsrc 2c19213,
587c7f4; avp2src M-X5, M-X6).

## 8. Where the fixes are

- Microsoft DirectMusic with registration-free COM: nolfsrc M-P4-12,
  0a57051, e9755a0; avp2src M-X4, a255a4b; tools 314d71c.
- MP3 decoded in the sound driver (minimp3): cjacksrc EN-50, 03998c2.
- MP3 codec for the legacy build under Wine: cjacksrc APPS-50, 6ffbb72,
  03998c2.
- No sound driver, call through a null pointer: nolf2src M-E64, 19855c4;
  cjacksrc EN-7, a8b8cf0.
- Empty and placeholder sound names: nolfsrc M-P5-22; RETAIL_BUGS.md
  "Empty and placeholder sound names fill the console with errors";
  0c7c80d.
- Music moods above 100 frames a second: nolf2src M-G30, 4512257,
  98a3d0c; cjacksrc GAME-40, adbbad6.
- COM on the DirectMusic notification thread: nolf2src M-E66, ead8b86.
- `StopSecondary` and `StopMotif` loop: nolfsrc RETAIL_BUGS.md, e7f5442;
  nolf2src M-E7, 65560a4.
- Untested transition segment state: cjacksrc EN-5, 9bb4661.
- Music thread handle not closed: cjacksrc EN-4, 9bb4661.
- Transition index out of range: cjacksrc EN-60, 0e7420a.
- DirectMusic notification not freed: avp2src RETAIL_BUGS.md
  "DirectMusic notifications leak on a segment that is not the newest",
  4dea255.
- `InitLevel` path leak: nolfsrc RETAIL_BUGS.md, ebc472b.
- `InitLevel` trace typo: nolfsrc 1d91064; nolf2src M-E9.
- `CMusicMgr::SetMood` reads before its level table: nolf2src M-G14,
  d88af65.
- 3D voice count from an uninitialised value: avp2src M-B109, M-X7,
  19ee00d.
- Inverted filter name comparison (Miles filters): nolfsrc RETAIL_BUGS.md
  "`CSoundMgr::GetFilterIndex`: the name comparison is inverted", fdd770d.
- Positioned sounds silent from a wrong vtable slot (reconstruction):
  nolfsrc 4db6cda; avp2src 19ee00d.
- OpenMiles measured against Miles 6.0i: nolfsrc 2c19213, 587c7f4,
  959bd86, e205a3f; avp2src M-X5, M-X6, a255a4b.
- Not fixed: Tron 2.0 `SndDrv.dll` mutex that nothing creates, and the
  missing-codec message that names the wrong codec (tron20src
  RETAIL_BUGS.md).
