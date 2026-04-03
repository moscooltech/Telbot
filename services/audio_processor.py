import numpy as np
import soundfile as sf

def process_audio(input_file, output_file):
    try:
        # Read the input audio file
        data, sample_rate = sf.read(input_file)
        if sample_rate != 22050:
            raise ValueError(f"Sample rate must be 22050 Hz, got {sample_rate} Hz")

        # Optimize for narration-only audio
        # For this example, let's just simulate processing
        narration_data = data  # Assume we process to isolate narration

        # Write out the `narration_data` to output file with low bitrate
        sf.write(output_file, narration_data, 22050, 'PCM_16', 64)

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Perform any required memory cleanup
erased_data = None  # To simulate cleanup

# Example usage
# process_audio('path/to/input/file.wav', 'path/to/output/file.wav')
