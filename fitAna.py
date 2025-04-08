import os
from fitdecode import FitReader

def calculate_max_power_per_speed(fit_file_path):
    """
    Reads a .fit file, calculates W/s, and returns the maximum value.
    """
    max_watts_per_second = 0.0
    power_data = []
    speed_data = []

    try:
        with open(fit_file_path, 'rb') as fit_file:
            fit_reader = FitReader(fit_file)
            for frame in fit_reader:
                if frame.frame_type == 'record':
                    record_data = frame.fields
                    power = None
                    speed = None

                    for data in record_data:
                        if data.name == 'power' and data.value is not None:
                            power = data.value
                        elif data.name in ['speed', 'enhanced_speed'] and data.value is not None:
                            speed = data.value
                        elif data.name == 'velocity' and data.value is not None:
                            speed = data.value  # Assuming m/s

                    if power is not None and speed is not None and speed > 0:
                        watts_per_second = power / speed
                        max_watts_per_second = max(max_watts_per_second, watts_per_second)

    except FileNotFoundError:
        print(f"Error: File not found: {fit_file_path}")
        return None
    except Exception as e:
        print(f"Error processing file {fit_file_path}: {e}")
        return None

    return max_watts_per_second

def process_directory(directory_path):
    """
    Processes all .fit files in the given directory.
    """
    results = {}
    for filename in os.listdir(directory_path):
        if filename.endswith(".fit"):
            file_path = os.path.join(directory_path, filename)
            max_w_s = calculate_max_power_per_speed(file_path)
            if max_w_s is not None:
                results[filename] = max_w_s
    return results

if __name__ == "__main__":
    directory = input("Enter the directory containing the .fit files: ")
    if os.path.isdir(directory):
        powercurve_data = process_directory(directory)
        if powercurve_data:
            print("\nMaximum W/s per file:")
            for filename, max_w_s in powercurve_data.items():
                print(f"{filename}: {max_w_s:.2f} W/s")
        else:
            print("No .fit files found in the directory or an error occurred.")
    else:
        print("Invalid directory path.")