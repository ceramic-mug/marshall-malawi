import os
import subprocess
import sys

def convert_and_compress(directory="photos_for_gallery"):
    if not os.path.exists(directory):
        print(f"Directory '{directory}' not found. Please create it or specify a different one.")
        return

    print(f"Processing images in '{directory}'...")
    
    # Extensions to look for
    exts = ('.heic', '.HEIC')
    
    count = 0
    for filename in os.listdir(directory):
        if filename.endswith(exts):
            filepath = os.path.join(directory, filename)
            # Create new filename with .jpg extension
            new_filename = os.path.splitext(filename)[0] + ".jpg"
            new_filepath = os.path.join(directory, new_filename)
            
            print(f"Converting {filename} -> {new_filename}...")
            
            # Use 'sips' (scriptable image processing system) built-in on macOS
            # -s format jpeg: Convert to JPEG
            # -s formatOptions 75: Set quality to 75% (good for web)
            # -Z 1600: Resample so max dimension is 1600px (good for web optimization)
            try:
                subprocess.run([
                    "sips", 
                    "-s", "format", "jpeg", 
                    "-s", "formatOptions", "75", 
                    "-Z", "1600", 
                    filepath, 
                    "--out", new_filepath
                ], check=True, capture_output=True)
                
                count += 1
            except subprocess.CalledProcessError as e:
                print(f"Error converting {filename}: {e}")

    print(f"\nDone! Converted and optimized {count} images.")

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "photos_for_gallery"
    convert_and_compress(target_dir)
