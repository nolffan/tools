# 21 · DirectInput

This guide tells you how to find, name and reconstruct DirectInput code
in a game of the DirectX 5 to 9 period. It also tells you what breaks
in that code on modern systems, and how to fix it in a modern build.

The rule that this guide teaches first:

> **The name of a DirectInput object is display text. It is not an
> identifier.** Find an object by its type and its instance number or
> its data offset. Show its name, but do not store it or compare it.

Section 5 is a worked example of this rule. The examples are from the
LithTech games of our projects. For the general method of a modern
build, see [18 · Building a modern variant](18_modern_builds.md). This
guide does not repeat it.

## 1. Recognise DirectInput in a binary

### Imports

DirectInput has one entry point for each generation:

| DLL | Entry point | Interfaces |
|---|---|---|
| `DINPUT.dll` | `DirectInputCreateA` / `W` / `Ex` | `IDirectInput`, `2`, `7`; `IDirectInputDevice`, `2`, `7` |
| `DINPUT8.dll` | `DirectInput8Create` | `IDirectInput8`, `IDirectInputDevice8` |

The import is usually the only call into the DLL. All other calls go
through the vtables of the interfaces. Example: in NOLF, `0x0048db30` is
`jmp *0x004a1000`, the thunk for `DINPUT.dll!DirectInputCreateA`
(nolfsrc `src/engine/lithtech/worldtree.cpp`).

### GUIDs in `.rdata`

The GUIDs come from `dxguid.lib` (or from the header with `INITGUID`).
They are data, not code. Name each one from the bytes in the SDK
header. These GUIDs are the usual anchors:

- `GUID_SysMouse` `{6F1D2B60-D5A0-11CF-BFC7-444553540000}` and
  `GUID_SysKeyboard` `{6F1D2B61-...}`.
- `GUID_XAxis` .. `GUID_POV`: `{A36D02E0..F2-C9F3-11CF-BFC7-444553540000}`.
  The code compares an object's `guidType` against them.
- The IID that the code gives to `QueryInterface`, for example
  `IID_IDirectInputDevice2A`. It tells you the interface version.

Example: in NOLF, `0x004a3a4c` and `0x004a3a5c` are `GUID_SysKeyboard`
and `GUID_SysMouse`, and `0x004a3b1c` is `IID_IDirectInputDevice2A`
(nolfsrc `clientinput.cpp`, header comment).

### Data formats are statically linked data

`c_dfDIKeyboard`, `c_dfDIMouse`, `c_dfDIMouse2`, `c_dfDIJoystick` and
`c_dfDIJoystick2` are not in the DLL. They are data objects in
`dinput.lib` or `dinput8.lib`, and the linker copies them into the
image. Each one is a `DIDATAFORMAT` followed by its table of
`DIOBJECTDATAFORMAT` rows.

Screen them as middleware. Do not reconstruct them. If a function
enumerator lists one as a function, it is an extent defect.

Example: the NOLF function table had a "704-byte function" at
`0x0048db40`. It had no `ret`, and nothing called it. The only
reference was a dword at `0x004a3928`. The five dwords before that
reference are a `DIDATAFORMAT`:

```
0x004a3914  0x00000018  dwSize      = 24
0x004a3918  0x00000010  dwObjSize   = 16
0x004a391c  0x00000001  dwFlags     = DIDF_ABSAXIS
0x004a3920  0x00000050  dwDataSize  = sizeof(DIJOYSTATE) = 80
0x004a3924  0x0000002c  dwNumObjs   = 44
0x004a3928  0x0048db40  rgodf       (44 x 16 = 704 bytes)
```

Thus the row was `c_dfDIJoystick` (nolfsrc `worldtree.cpp`, "EXTENT
DEFECT").

NOTE: The Rich header also shows these objects. In NOLF 2,
`dinput8.lib` is five C objects of build 9178 and one import
descriptor. Two of the C objects in `Lithtech.exe` are the keyboard and
mouse formats (nolf2src `progress/COMPILERS.md`). To prove such a claim,
link a small test program against the SDK library and compare the Rich
headers.

## 2. COM calls in the disassembly

DirectInput methods are `__stdcall`. The caller pushes `this` as the
first argument. It does not put `this` in `ecx`. Thus declare the
interfaces with the SDK macros (`STDMETHOD`), not as `thiscall` classes.

A typical call (an example, not a retail address):

```asm
mov   eax, [esi]          ; esi = the device, eax = its vtable
push  ...                 ; the arguments, right to left
push  esi                 ; this
call  [eax+0x28]          ; GetDeviceData
```

The slot offsets follow the declaration order in `dinput.h`. Each
newer interface adds slots at the end:

| Offset | `IDirectInput` (A, 2, 7, 8) | `IDirectInputDevice` (A, 2, 7, 8) |
|---|---|---|
| 0x00-0x08 | `QueryInterface`, `AddRef`, `Release` | same |
| 0x0c | `CreateDevice` | `GetCapabilities` |
| 0x10 | `EnumDevices` | `EnumObjects` |
| 0x14 | `GetDeviceStatus` | `GetProperty` |
| 0x18 | `RunControlPanel` | `SetProperty` |
| 0x1c | `Initialize` | `Acquire` |
| 0x20 | `FindDevice` (2 and later) | `Unacquire` |
| 0x24 | `CreateDeviceEx` (7) or `EnumDevicesBySemantics` (8) | `GetDeviceState` |
| 0x28 | `ConfigureDevices` (8) | `GetDeviceData` |
| 0x2c | | `SetDataFormat` |
| 0x30 | | `SetEventNotification` |
| 0x34 | | `SetCooperativeLevel` |
| 0x38-0x44 | | `GetObjectInfo`, `GetDeviceInfo`, `RunControlPanel`, `Initialize` |
| 0x48-0x68 | | device 2: `CreateEffect` .. `Poll` (0x64), `SendDeviceData` (0x68) |
| 0x6c-0x7c | | device 7: effect files; device 8: action maps |

Check each offset against the header of the SDK that the game used.
The NOLF engine uses 0x0c and 0x10 of `IDirectInput`, and 0x08, 0x10,
0x1c, 0x20, 0x28, 0x2c and 0x34 of `IDirectInputDevice2` (nolfsrc
`clientinput.cpp`). For the general method, see
[07 · Naming anonymous functions from vtables](07_vtables.md).

### HRESULTs

Learn these values. You see them as immediates in `cmp` instructions:

| Value | Name | Meaning |
|---|---|---|
| 0 | `DI_OK` | success |
| 1 | `DI_BUFFEROVERFLOW` (also `DI_NOTATTACHED`, `DI_PROPNOEFFECT`) | success, but events were lost |
| 0x80070005 | `DIERR_OTHERAPPHASPRIO` | another window has the foreground |
| 0x8007000c | `DIERR_NOTACQUIRED` | the device is not acquired |
| 0x8007001e | `DIERR_INPUTLOST` | the acquisition was lost |

`DI_BUFFEROVERFLOW` is a success code. Code that tests `!= DI_OK` treats
it as a failure unless it tests it separately.

## 3. Find the SDK version

Three different things have a version. Find each one:

1. **The header.** `DIRECTINPUT_VERSION` before `#include <dinput.h>`
   selects the types and the struct sizes that compile.
2. **The run-time request.** The `dwVersion` argument to the create
   function. It can differ from the header.
3. **The interfaces.** The IIDs that the code asks for.

| Game | Header | Create call | Device interface |
|---|---|---|---|
| NOLF | VC6 `dinput.h` (DirectInput 5) | `DirectInputCreateA` 0x700, then 0x300 | `IDirectInputDevice2A` |
| AvP2 | DirectX 8.1 SDK, `DIRECTINPUT_VERSION 0x0700` | `DirectInputCreateA` 0x700, then 0x300 | `IDirectInputDevice2A` |
| NOLF 2, Contract J.A.C.K., Tron 2.0 | `DIRECTINPUT_VERSION 0x0800` | `DirectInput8Create` 0x0800 | `IDirectInputDevice8A` |

The sources are nolfsrc and avp2src `src/engine/lithtech/clientinput.cpp`
(`input_Init`), and `src/Engine/runtime/kernel/src/sys/win/input.cpp` of
the other three projects.

Other version evidence:

- **Device types.** Before version 8, `DIDEVTYPE_MOUSE` is 2,
  `KEYBOARD` 3 and `JOYSTICK` 4. In version 8, `DI8DEVTYPE_MOUSE` is
  0x12, `KEYBOARD` 0x13, `JOYSTICK` 0x14 and `GAMEPAD` 0x15. The
  comparison constant on `LOBYTE(dwDevType)` tells you which.
- **`dwSize` values.** The code stores the size of each struct before a
  call. Example: NOLF copies a `DIDEVICEOBJECTINSTANCEA` of 316 bytes
  (0x4f dwords) in its object matcher (nolfsrc `diblit.cpp`).

## 4. How a game uses a device

Most engines follow these steps. Find each one, because each one has
its own failure on modern systems:

1. **Create.** `CreateDevice(GUID_SysMouse)` or a GUID from
   `EnumDevices`.
2. **Set the cooperative level.** `DISCL_FOREGROUND | DISCL_NONEXCLUSIVE`
   is usual for the keyboard and the mouse. NOLF uses `DISCL_EXCLUSIVE`
   for a joystick only (nolfsrc `input_EnableDevice`).
3. **Set the data format.** A standard format (`c_dfDIMouse`) or a
   format that the engine builds from `EnumObjects`. The NOLF engine
   builds its own, one dword for each bound object (`dwOfs = 4*j`), and
   uses `c_dfDIJoystick` only for a joystick.
4. **Set the buffer size.** `SetProperty(DIPROP_BUFFERSIZE)`.
5. **Acquire.**
6. **Read each frame.** `GetDeviceData` (buffered events) or
   `GetDeviceState` (the state now). The engine maps each event to its
   object by `dwOfs`.
7. **Reacquire after an error.**
8. **Flush.** `GetDeviceData` with a null array and `INFINITE` items
   removes all events (NOLF `input_FlushDeviceData`, `0x00437b70`).

## 5. Worked example: mouse buttons bound by name

This is nolfsrc issue #59, fixed in nolfsrc fab2619 (MODERN.md
M-P1-33, two entries in RETAIL_BUGS.md).

### The symptom

A player said that the mouse buttons did nothing. The mouse turned the
view, and the wheel operated. After the game stopped, `autoexec.cfg`
did not contain the three lines for the mouse buttons.

### Follow the name

Find each place where an object name goes into the engine, and each
place where it comes out. In NOLF, these are the places:

1. A binding names a device and an object, for example
   `rangebind "##mouse" "Button 0" ...`.
2. `di_FindDeviceObject` (`0x00438140`) compares the name with the
   objects that already have a binding.
3. If none matches, `di_AddDeviceObject` (`0x00438470`) enumerates the
   objects of the device. Its callback (`0x00438ad0`) compares the name
   with `tszName`.
4. If no object matches, the engine creates no object. The binding
   fails, and the engine shows no message.
5. The config save (`cc_SaveInputBindings`, `0x00438d80`) writes only
   the bindings that have an object.

`tszName` comes from Windows and from the mouse driver. It is
`Button 0` on an English Windows. Another language or another driver
can give a different text. The default controls (`defctrls.cfg`) bound
the buttons as `"Button 0"`, `"Button 1"` and `"Button 2"`. Thus the
bindings did not attach, and the save dropped them.

The axes continued to operate because the defaults bound them by fixed
names: `##x-axis`, `##y-axis` and `##z-axis`.

### The retail aliases, and why they are not sufficient

A name that starts with `##` is an alias. The retail parse in NOLF is:

| Alias | Match |
|---|---|
| `##x-axis`, `##y-axis`, `##z-axis` | `guidType` is `GUID_XAxis` .. `GUID_ZAxis` |
| `##Button 0` .. `##Button 2` | `GUID_Button` and `dwOfs == DIMOFS_BUTTON0..2` |
| `##Slider 0/1`, `##POV 0..3` | the GUID and the joystick offset |
| `##<digits>` | `atoi` of the text: any object with that instance number |

The keyboard uses the last form: `##57` is the object with instance 57,
which is the scan code `DIK_SPACE`.

These aliases have two problems:

- **`dwOfs` is not certain.** `EnumObjects` gives the offset in the
  native format of the device, not in `c_dfDIMouse`. The `##Button N`
  alias works only if the two agree.
- **An instance number alone has no type.** The last form matches the
  first object with that instance, of any type. Thus `##button2` gives
  `atoi("button2")`, which is 0. On the system mouse, instance 0 is the
  X axis.

The second problem is also a retail bug in the NOLF 2 menus. They bind a
gamepad button as `##<instance>`. DirectInput numbers the axes and the
buttons of a HID gamepad each from 0. Thus button 1 binds the Y axis
(nolf2src RETAIL_BUGS.md, "A gamepad's buttons are bound by their
instance number"; the same code in Contract J.A.C.K.).

### The fix

Give each button a fixed name from its type and its place:

1. Enumerate the objects with `DIDFT_BUTTON`. Keep only `GUID_Button`.
2. The number of a button is the count of buttons with a lower
   `DIDFT_GETINSTANCE(dwType)`. This rank does not depend on the
   enumeration order or on `dwOfs`.
3. The fixed name is `##button<rank>`, for ranks 0 to 7.
4. Resolve a binding by any of three names: the fixed name, the
   DirectInput name, or the retail `Button <N>`.
5. Create the object by its real DirectInput name. Then the retail
   matcher finds it. Give the object the fixed name, so that the save
   writes the fixed name.
6. If a fixed name names a button that the mouse does not have, bind
   nothing. Do not let it fall through to the retail `atoi` parse.
7. Change the default controls to the fixed names.
8. Add a one-time config upgrade. A config with no mouse button bound
   gets the default buttons again (nolfsrc M-P1-12, version 1.8).

Continue to show `tszName` in the menus. It is correct as display text.

The code is `src/modern/engine/p1_mousebutton.cpp` and three hooks in
`clientinput.cpp` (`di_FindDeviceObject`, `input_AddTrigger`,
`input_EnableDevice`).

NOTE: Under Wine, the system mouse has its axes at instances 0 to 2 and
its buttons from 3. Thus the rank is the button number. This is not
yet confirmed on Windows. A HID device whose instance order is not its
physical order can give a different rank. Two buttons with the same
`tszName` match the first one.

### The second bug: a signed `char` to `iscntrl`

The Customize Controls menu binds a mouse button with a console command
that contains the DirectInput name. Some names with accented letters
did nothing.

The cause: the console parser (`parse_Token`, lithtech.exe `0x0041b710`,
server.dll `0x10005e24`) calls `iscntrl(c)` with a signed `char`. A
character above 127 is negative. The C library of VC6 uses it as an
index before its type table, `_pctype`. Some of those bytes have the
`_CONTROL` bit (0x20). Then the parser ends the command at that
character. The command has too few arguments, and it fails with no
message. The menu shows the binding all the same.

To find the bad characters, do these steps:

1. Find `_ctype` in the file image by its first words: `0000`, nine
   `0020`, then `0028`, `0028`.
2. For each byte b from 128 to 255, read the word at
   `_pctype + 2*(b-256)`.
3. List the bytes where the word has bit 0x20.

In the retail lithtech.exe, 22 bytes have the bit, for example 0xDF
(German "ß" in code page 1252) and 0xE0 (Russian "а" in code page 1251).
Our modern release build before the fix had 41, for example 0xF3
(Spanish "ó"). The list changes with each link, because it depends on
the data that the linker puts before the table.

The fix is `iscntrl((unsigned char)c)`. The LithTech engine of NOLF 2,
Contract J.A.C.K. and Tron 2.0 has its own fix of this bug,
`Parse_Iscntrl` in `src/Engine/runtime/shared/src/conparse.cpp`, with a
developer comment about it. The AvP2 engine has the retail form
(avp2src `src/engine/server/console.cpp`, `parse_Token`). It is not
verified that each shipped binary agrees with its source release.

CAUTION: Look for this bug in all code that takes a localised string
from the system. `is*` and `to*` functions with a signed `char` are
undefined for values above 127.

### The rules from this example

- Store and compare objects by type and instance number, or by type and
  data offset. Never by `tszName` or `tszInstanceName`.
- Never match by instance number without the type.
- Read old configs that use names. Write only the stable form.
- Make a binding failure visible, at least in a log.
- Test with names that are not English and not ASCII (section 7).

## 6. What breaks today

Each item gives the symptom, the cause, the fix, the test and an
example. Guide 18 gives the general method for some of them. This
section gives the DirectInput detail.

### 6.1 Device enumeration crashes

- **Symptom:** the game crashes at startup, before its window opens.
  The fault is an access violation in `RtlAllocateHeap` inside
  `dinput.dll`, on some Windows 11 machines.
- **Cause:** `EnumDevices` examines every HID device on the machine.
- **Fix:** if the game reads no DirectInput joystick, do not call
  `EnumDevices`. Create the devices with `GUID_SysKeyboard` and
  `GUID_SysMouse`. Fill the device records from `GetDeviceInfo`. It
  gives the same name, GUID and type as the enumeration. Thus the
  bindings find the same devices. Enumerate only for a console command
  that lists the devices.
- **Test:** under Wine, rebind a key and play. The crashed Windows
  machine is not yet tested again.
- **Examples:** nolfsrc M-P7-09 (2acdef1), nolf2src M-E33 (8c4b739),
  cjacksrc EN-22 (9bd638a), avp2src M-7 (a5c8c9f).

### 6.2 Focus loss and Alt+Tab

With `DISCL_FOREGROUND`, DirectInput removes the acquisition when the
window loses the foreground. `Acquire` then fails with
`DIERR_OTHERAPPHASPRIO` until the window is in front again. The next
read fails with `DIERR_INPUTLOST` or `DIERR_NOTACQUIRED`.

The LithTech engines handle this in the read: on any error except
`DI_BUFFEROVERFLOW`, they call `Acquire` one time and read again
(nolfsrc `input_ReadActions`; nolf2src `input_ReadInput`). They do not
use `WM_ACTIVATE` for input. This pattern is sufficient. Keep it.

The Alt+Tab faults that we found were in the renderer and the sound,
not in DirectInput. Example: AvP2 stopped the renderer and held the
sounds on `WM_ACTIVATEAPP`, and under Wine they did not come back
(avp2src M-21, b06b6fc; nolf2src M-G41).

A fake device must copy this behaviour. It must refuse `Acquire` while
the window is not in the foreground (nolfsrc `p7_gamepad.cpp`).

### 6.3 Mouse look that changes with the frame rate

- **Symptom:** the mouse turns the view further at a high frame rate,
  and it is not smooth.
- **Cause:** the engine reads one buffered event at a time
  (`nEvents = 1` for the mouse, with the comment "fixes the USB mouse
  lockups"). It keeps the last value of an axis and adds it again on
  later passes and in later frames.
- **Fix:** read the full buffer. Add the events of each axis. Use the
  sum one time. Make the buffer large enough for a 1000 Hz mouse. See
  [18](18_modern_builds.md#the-mouse) for the steps.
- **Test:** move the pointer with `xdotool` in fixed steps, and compare
  the turn with the release build.
- **Examples:** nolf2src M-E3 (a4e674c); the bug is in nolf2src
  RETAIL_BUGS.md, "Mouse look overshoots", and avp2src RETAIL_BUGS.md,
  "The mouse look turns further at a higher frame rate".

When you model such code, model it exactly. The nolf2src entry used a
byte-identical model of the function to measure 1.06 to 3.8 times the
correct turn at different rates.

### 6.4 Raw input in place of the DirectInput mouse

Use `WM_INPUT` when you do not want to change the engine's mouse path,
or when the fix of 6.3 is not sufficient. The look then reads the mouse
motion itself, and DirectInput continues to give the buttons and the
wheel to the bindings.

Our design:

1. Find `RegisterRawInputDevices` and `GetRawInputData` with
   `GetProcAddress`. Declare the types by hand for an old SDK.
2. Register usage page 1, usage 2 (the mouse) with flags 0. Do not set
   `RIDEV_NOLEGACY`. Then the DirectInput buttons and wheel continue to
   operate.
3. Add the relative motion between frames. Convert absolute motion (a
   tablet, a remote desktop) into relative motion.
4. Hide the cursor and clip it to the window in play. Release it in the
   menus.
5. Keep the retail path behind a setting (`OldMouseLook 1`), and give a
   fallback from cursor motion (`NoRawInput 1`).

Examples: nolfsrc M-P1-03 (7f1884d), avp2src M-6 (538922a). Under Wine,
the DirectInput buttons and wheel operate with this registration. This
is not verified on Windows.

### 6.5 Joysticks, and XInput through a fake device

DirectInput joysticks have no dead zone and no hot-plug. They put the
two triggers of an Xbox pad on one axis. Under Wine, one pad can show as
more than one device.

The fix: implement the device interface of the engine, for example
`IDirectInputDevice2A` or `IDirectInputDevice8A`, and answer from
XInput. See [18](18_modern_builds.md#modern-controllers-through-an-adapter)
for the general steps. The DirectInput detail:

- Give the device a GUID of its own, and a device type that the engine
  reads as a joystick or a gamepad.
- Give fixed object names. Here the names are ours, so the menus can
  bind by name safely.
- Answer `EnumObjects`, `GetObjectInfo` and `GetCapabilities` with the
  axes and the buttons, with correct `dwType` instance numbers.
- Store events as `DIDEVICEOBJECTDATA` in the data format that the
  engine sets, standard or its own.
- Remove the DirectInput joysticks from the device list
  (`DI8DEVTYPE_JOYSTICK` .. `DI8DEVTYPE_1STPERSON`).

Examples: nolfsrc M-P7-01 (a99873c), nolf2src M-E20 and M-E21
(8587813), cjacksrc EN-20 and EN-21 (9bd638a), avp2src M-7 (a5c8c9f).
The scan of empty slots on a thread is nolf2src M-E59 (0775117).

### 6.6 Menu bindings of joystick and gamepad controls

Look at the code that binds the control that the player pushed. It
often chooses between a code and a name by the device type. Examples:

- NOLF 2 and Contract J.A.C.K. bind a gamepad button by instance number
  alone, thus to an axis (nolf2src M-G63, 8587813; cjacksrc CL-24,
  9bd638a).
- AvP2 removes the old binding by code, but binds a joystick button by
  name. Thus the old binding stays (avp2src RETAIL_BUGS.md, "Binding a
  joystick button in Customize Controls leaves its old command bound
  too"; M-7, a5c8c9f).

### 6.7 The keyboard: scan codes and layouts

A `DIK_` code is a scan code. It is the position of a key, not its
character. The LithTech menus bind keys by code (`##57`), which is
correct. Two consequences:

- The key names in the menus come from `tszName`, and they are
  localised. Show them, but do not bind by them. In NOLF, Customize
  Controls removes the old binding of a key by its name (nolfsrc
  RETAIL_BUGS.md, the `iscntrl` entry).
- A default key that is chosen by its character can be in a different
  place, or absent. Example: the console key `DIK_GRAVE` (`##41`) is not
  the backquote on all layouts. nolfsrc M-P2-15 (82d0759) adds Shift+Esc
  as a second console key.

## 7. Test input under Wine and Xvfb

Run the game under Xvfb with scripted input. `tools/playtest.sh` reads
a script of commands (`window`, `wait`, `key`, `type`, mouse moves and
clicks) and sends them with `xdotool`. See
[05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute).

Do these steps for an input test:

1. Start each run from the same state: the shipped `autoexec.cfg` and an
   empty save directory.
2. Send a harmless key first, for example Down. The NOLF menus ignore the
   first key or click after the intro movies.
3. To test a config save, stop the game with the console command `quit`.
   Then the engine writes `autoexec.cfg`. Compare the file.
4. For a controller, use a test pad: a file that gives the pad state
   (`NOLFSRC_PADTEST`, `NOLF2SRC_PADTEST`, `CJACKSRC_PADTEST`,
   `AVP2SRC_PADTEST`), and the `pad` and `tap` script commands.

### Test hooks for system data

Wine gives English names. To test the names of another Windows, wrap
the real device in a test hook:

1. In the debug build only, wrap the device from `CreateDevice` in a
   class that implements the same interface.
2. Send each call to the real device.
3. Change only the data under test. In nolfsrc, `EnumObjects` and
   `GetObjectInfo` give each button the name from
   `NOLFSRC_TEST_MOUSENAMES`, a `printf` format such as `Taste %d`.
4. Make sure that the release binary does not contain the hook.

For non-ASCII names, set `LC_ALL=C.UTF-8` in the container. If not,
Wine changes the accented letters.

With `Taste %d`, the build before the fix dropped the three lines from
`autoexec.cfg`. With `Botón %d`, a binding made in Customize Controls
was lost. After the fix, both tests passed (nolfsrc M-P1-33).

NOTE: These items are not yet tested on Windows: the names that a
localised Windows or a driver really gives, the instance order of the
Windows system mouse, and DirectInput together with raw input.

## 8. Where the fixes are

| Fix | Project and id | Retail bug entry | Commit |
|---|---|---|---|
| Mouse buttons by fixed names | nolfsrc M-P1-33 | "The default mouse buttons are bound by names that Windows can change" | fab2619 |
| `iscntrl` with an unsigned `char` | nolfsrc M-P1-33 | "The console ends a command at some characters above 127" | fab2619 |
| `iscntrl`, port candidate | avp2src `src/engine/server/console.cpp` (`parse_Token`, two calls) | -- | not fixed |
| No device enumeration | nolfsrc M-P7-09; nolf2src M-E33; cjacksrc EN-22; avp2src M-7 | -- | 2acdef1; 8c4b739; 9bd638a; a5c8c9f |
| Mouse buffer read whole and summed | nolf2src M-E3 | "Mouse look overshoots, unevenly, and more at high frame rates" | a4e674c |
| Raw mouse input | nolfsrc M-P1-03; avp2src M-6 | avp2src "The mouse look turns further at a higher frame rate" | 7f1884d; 538922a |
| XInput as a fake device, no DirectInput joysticks | nolfsrc M-P7-01; nolf2src M-E20, M-E21; cjacksrc EN-20, EN-21; avp2src M-7 | -- | a99873c; 8587813; 9bd638a; a5c8c9f |
| No controller scan in the frame | nolf2src M-E59 | -- | 0775117 |
| Gamepad buttons bound by instance number | nolf2src M-G63; cjacksrc CL-24 | "A gamepad's buttons are bound by their instance number"; "A gamepad's buttons are bound to its axes" | 8587813; 9bd638a |
| Joystick button keeps its old command | avp2src M-7 | "Binding a joystick button in Customize Controls leaves its old command bound too" | a5c8c9f |
| Second console key for other layouts | nolfsrc M-P2-15 | -- | 82d0759 |
| Alt+Tab in a window (renderer and sound) | avp2src M-21 | "Alt+Tab freezes the picture" | b06b6fc |
