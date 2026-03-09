# FFmpeg Patterns for Reel Building

Quick reference for common ffmpeg operations in the pipeline.

## Table of Contents
1. Probe metadata
2. Scale to 9:16 vertical
3. Extract frame at timestamp
4. Cut segment (video only)
5. Cut segment (audio only)
6. Concat segments
7. Merge video + audio
8. Text overlay (drawtext)
9. Compress for API upload
10. Crop/zoom a frame region
11. Extract raw audio PCM

---

## 1. Probe metadata
```bash
ffprobe -v error -show_entries format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_name -of json "INPUT.mov"
```

## 2. Scale to 9:16 vertical (1080x1920)
```bash
SCALE="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
```
This scales the shortest dimension to fill 1080x1920, then center-crops the excess. Works for both landscape and portrait source footage.

## 3. Extract frame at timestamp
```bash
ffmpeg -v error -ss TIMESTAMP -i "INPUT.mov" -vframes 1 -q:v 2 "frame.jpg" -y
```
Use `-q:v 1` for highest quality (larger file).

## 4. Cut segment (video only, no audio)
```bash
ffmpeg -v error -ss START -i "SOURCE.mov" -t DURATION \
  -vf "$SCALE" -an -c:v libx264 -preset fast -crf 23 -r 30 "segment.mp4" -y
```

## 5. Cut audio segment
```bash
ffmpeg -v error -i "SOURCE.mov" -ss START -t DURATION \
  -vn -c:a aac -b:a 128k "audio.aac" -y
```

## 6. Concat segments
Create a text file listing segments:
```
file 'seg1.mp4'
file 'seg2.mp4'
file 'seg3.mp4'
```
Then:
```bash
ffmpeg -v error -f concat -safe 0 -i concat.txt -c copy "output.mp4" -y
```

## 7. Merge video + audio
```bash
ffmpeg -v error -i "video.mp4" -i "audio.aac" \
  -c:v copy -c:a aac -shortest -movflags +faststart "output.mp4" -y
```

## 8. Text overlay (drawtext)
Single overlay:
```bash
ffmpeg -v error -i input.mp4 \
  -vf "drawtext=text='hello':fontfile=/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf:\
fontsize=60:fontcolor=white:borderw=3:bordercolor=black@0.8:\
x=200:y=500:enable='between(t,5,8)'" \
  -c:a copy -movflags +faststart output.mp4 -y
```

Multiple overlays (chain with commas):
```bash
-vf "drawtext=...:enable='between(t,5,8)',\
     drawtext=...:enable='between(t,15,18)'"
```

## 9. Compress for API upload
```bash
ffmpeg -v error -i "INPUT.mov" \
  -vf "scale=320:-2" -r 24 -c:v libx264 -crf 30 \
  -c:a aac -b:a 64k "compressed.mp4" -y
```

## 10. Crop/zoom a frame region
```bash
# Quadrant crops (1080x1920 source)
ffmpeg -v error -i frame.jpg -vf "crop=540:960:0:0" top_left.jpg -y      # top-left
ffmpeg -v error -i frame.jpg -vf "crop=540:960:540:0" top_right.jpg -y   # top-right
ffmpeg -v error -i frame.jpg -vf "crop=540:960:0:960" bot_left.jpg -y    # bottom-left
ffmpeg -v error -i frame.jpg -vf "crop=540:960:540:960" bot_right.jpg -y # bottom-right

# Arbitrary region: crop=W:H:X:Y
ffmpeg -v error -i frame.jpg -vf "crop=600:700:100:300" region.jpg -y
```

## 11. Extract raw audio PCM
```bash
ffmpeg -v error -i "INPUT.mov" -ac 1 -ar 8000 -f s16le -acodec pcm_s16le pipe:1 > audio.pcm
```
Produces signed 16-bit little-endian mono at 8kHz. Good for beat analysis.
