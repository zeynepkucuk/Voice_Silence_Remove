import collections
import contextlib
import sys
import wave
import webrtcvad

def read_wave(path):
    with contextlib.closing(wave.open(path, 'rb')) as wf:
        num_channels = wf.getnchannels()
        assert num_channels == 1
        sample_width = wf.getsampwidth()
        assert sample_width == 2
        sample_rate = wf.getframerate()
        assert sample_rate in (8000, 16000, 32000, 48000)
        pcm_data = wf.readframes(wf.getnframes())
        return pcm_data, sample_rate


def write_wave(path, audio, sample_rate):
    with contextlib.closing(wave.open(path, 'wb')) as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio)


class Frame(object):

    def __init__(self, bytes, timestamp, duration):
        self.bytes = bytes
        self.timestamp = timestamp
        self.duration = duration


def frame_generator(frame_duration_ms, audio, sample_rate):
    n = int(sample_rate * (frame_duration_ms / 1000.0) * 2)
    offset = 0
    timestamp = 0.0
    duration = (float(n) / sample_rate) / 2.0
    while offset + n < len(audio):
        yield Frame(audio[offset:offset + n], timestamp, duration)
        timestamp += duration
        offset += n


def vad_collector(sample_rate, frame_duration_ms,
                  padding_duration_ms, vad, frames):
    """
    Arguments:
    sample_rate = The audio sample rate, in Hz.
    frame_duration_ms = The frame duration in milliseconds.
    padding_duration_ms = The amount to pad the window, in milliseconds.
    vad = An instance of webrtcvad.Vad.
    frames = a source of audio frames (sequence or generator).
    Returns: A generator that yields PCM audio data.
    """

    num_padding_frames = int(padding_duration_ms / frame_duration_ms)
    # i use a deque for our sliding window/ring buffer.
    ring_buffer = collections.deque(maxlen=num_padding_frames)

    triggered = False

    voiced_frames = []
    for frame in frames:
        is_speech = vad.is_speech(frame.bytes, sample_rate)

        sys.stdout.write('1' if is_speech else '0')
        if not triggered:
            ring_buffer.append((frame, is_speech))
            num_voiced = len([f for f, speech in ring_buffer if speech])

            if num_voiced > 0.9 * ring_buffer.maxlen:
                triggered = True
                sys.stdout.write('+(%s)' % (ring_buffer[0][0].timestamp,))

                for f, s in ring_buffer:
                    voiced_frames.append(f)
                ring_buffer.clear()
        else:
            # We're in the TRIGGERED state, so collect the audio data and add it to the ring buffer.
            voiced_frames.append(frame)
            ring_buffer.append((frame, is_speech))
            num_unvoiced = len([f for f, speech in ring_buffer if not speech])

            if num_unvoiced > 0.9 * ring_buffer.maxlen:
                sys.stdout.write('-(%s)' % (frame.timestamp + frame.duration))
                triggered = False
                yield b''.join([f.bytes for f in voiced_frames])
                ring_buffer.clear()
                voiced_frames = []
    if triggered:
        sys.stdout.write('-(%s)' % (frame.timestamp + frame.duration))
    sys.stdout.write('\n')

    if voiced_frames:
        yield b''.join([f.bytes for f in voiced_frames])


def main(args):
    if len(args) != 2:
        sys.stderr.write(
            'Usage: Silence-Remove.py <aggressiveness> <path to wav file>\n'
            'Set the aggressiveness mode which is an integer between 0 and 3. 0 is the least aggressive about filtering out non-speech 3 is the most aggressive.')
        sys.exit(1)
    audio, sample_rate = read_wave(args[1])
    vad = webrtcvad.Vad(int(args[0]))
    frames = frame_generator(30, audio, sample_rate)
    frames = list(frames)
    segments = vad_collector(sample_rate, 30, 300, vad, frames)

    concataudio = [segment for segment in segments]

    joinedaudio = b"".join(concataudio)

    write_wave("Non-Silenced-Audio.wav", joinedaudio, sample_rate)

if __name__ == '__main__':
    main(sys.argv[1:])
