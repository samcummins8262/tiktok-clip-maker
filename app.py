"""
TikTok Clip Maker - Web Application Backend
Flask server that processes YouTube videos and creates TikTok clips
"""

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import os
import subprocess
import json
import re
import time
import threading
from pathlib import Path
from datetime import datetime
import uuid

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'processing'
OUTPUT_FOLDER = 'output'
MAX_CLIPS = 10

# Create folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Store job status
jobs = {}

# Viral keywords for detecting good moments
VIRAL_KEYWORDS = [
    'incredible', 'amazing', 'shocking', 'unbelievable', 'secret',
    'mistake', 'truth', 'revealed', 'never', 'always', 'everyone',
    'nobody', 'best', 'worst', 'crazy', 'insane', 'mind-blowing',
    'why', 'how', 'what if', 'imagine', 'should you', 'can you',
    'must', 'need to', 'have to', 'warning', 'danger', 'ultimate'
]


def srt_to_seconds(srt_time):
    """Convert SRT timestamp to seconds"""
    time_parts = srt_time.replace(',', '.').split(':')
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = float(time_parts[2])
    return hours * 3600 + minutes * 60 + seconds


def seconds_to_srt(seconds):
    """Convert seconds to SRT timestamp"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt(srt_path):
    """Parse SRT subtitle file"""
    if not os.path.exists(srt_path):
        return []
    
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?:\n\n|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    transcript = []
    for match in matches:
        start_time = srt_to_seconds(match[1])
        end_time = srt_to_seconds(match[2])
        text = match[3].replace('\n', ' ').strip()
        
        transcript.append({
            'start': start_time,
            'end': end_time,
            'text': text
        })
    
    return transcript


def get_video_duration(video_path):
    """Get video duration in seconds"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 0


def detect_viral_moments(transcript, duration):
    """Detect potential viral moments in the video"""
    moments = []
    
    if not transcript or duration == 0:
        # No transcript - create clips at regular intervals
        num_clips = min(int(duration / 60), MAX_CLIPS)
        for i in range(num_clips):
            start = i * (duration / num_clips)
            moments.append({
                'start': start,
                'end': min(start + 60, duration),
                'score': 0.5,
                'text': 'Interval clip'
            })
        return moments
    
    # Analyze transcript for viral content
    for i, segment in enumerate(transcript):
        score = 0
        text_lower = segment['text'].lower()
        
        # Check for viral keywords
        for keyword in VIRAL_KEYWORDS:
            if keyword in text_lower:
                score += 0.3
        
        # Questions get points
        if '?' in segment['text']:
            score += 0.2
        
        # Excitement (exclamations)
        if '!' in segment['text']:
            score += 0.15
        
        # If this segment has potential
        if score >= 0.3:
            # Look ahead to create 60-second clip
            end_time = segment['start'] + 60
            if end_time > duration:
                end_time = duration
            
            # Find natural ending point
            for j in range(i, len(transcript)):
                if transcript[j]['end'] >= end_time:
                    end_time = transcript[j]['end']
                    break
            
            clip_duration = end_time - segment['start']
            
            # Prefer 45-75 second clips
            if 45 <= clip_duration <= 75:
                moments.append({
                    'start': segment['start'],
                    'end': end_time,
                    'score': score,
                    'text': segment['text'][:100]
                })
    
    # Sort by score and remove overlaps
    moments.sort(key=lambda x: x['score'], reverse=True)
    
    filtered = []
    for moment in moments:
        # Check for overlap with already selected moments
        overlap = False
        for selected in filtered:
            if moment['start'] < selected['end'] and moment['end'] > selected['start']:
                overlap = True
                break
        
        if not overlap:
            filtered.append(moment)
        
        if len(filtered) >= MAX_CLIPS:
            break
    
    return filtered


def create_clip(video_path, start_time, end_time, output_path, transcript):
    """Create a TikTok-style clip with captions"""
    
    # Get captions for this time range
    clip_captions = [
        seg for seg in transcript 
        if seg['start'] >= start_time and seg['end'] <= end_time
    ]
    
    # Create SRT file for this clip
    srt_path = output_path.replace('.mp4', '.srt')
    with open(srt_path, 'w', encoding='utf-8') as f:
        for idx, caption in enumerate(clip_captions, 1):
            adjusted_start = caption['start'] - start_time
            adjusted_end = caption['end'] - start_time
            
            f.write(f"{idx}\n")
            f.write(f"{seconds_to_srt(adjusted_start)} --> {seconds_to_srt(adjusted_end)}\n")
            f.write(f"{caption['text']}\n\n")
    
    # Create the clip with TikTok-style captions
    cmd = [
        'ffmpeg', '-i', video_path,
        '-ss', str(start_time),
        '-t', str(end_time - start_time),
        '-vf', (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            f"subtitles='{srt_path}':force_style='"
            "FontName=Arial Black,"
            "FontSize=32,"
            "PrimaryColour=&H0000E7FF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H80000000,"
            "BorderStyle=1,"
            "Outline=4,"
            "Shadow=2,"
            "MarginV=100,"
            "Alignment=2,"
            "Bold=-1,"
            "Italic=-1'"
        ),
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-y',
        output_path
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except Exception as e:
        print(f"Error creating clip: {e}")
        return False


def process_video_job(job_id, youtube_url):
    """Background job to process video"""
    try:
        jobs[job_id]['status'] = 'downloading'
        jobs[job_id]['progress'] = 10
        
        # Create job folder
        job_folder = os.path.join(UPLOAD_FOLDER, job_id)
        os.makedirs(job_folder, exist_ok=True)
        
        # Download video
        output_template = os.path.join(job_folder, '%(id)s.%(ext)s')
        cmd = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            '--write-info-json',
            '--write-auto-sub',
            '--sub-lang', 'en',
            '--convert-subs', 'srt',
            youtube_url
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Find downloaded video
        video_files = list(Path(job_folder).glob('*.mp4'))
        if not video_files:
            raise Exception("Download failed")
        
        video_path = str(video_files[0])
        
        jobs[job_id]['status'] = 'analyzing'
        jobs[job_id]['progress'] = 30
        
        # Get video info
        duration = get_video_duration(video_path)
        srt_path = video_path.replace('.mp4', '.en.srt')
        transcript = parse_srt(srt_path)
        
        # Get video title
        info_file = video_path.replace('.mp4', '.info.json')
        video_title = "Video"
        if os.path.exists(info_file):
            with open(info_file, 'r') as f:
                info = json.load(f)
                video_title = info.get('title', 'Video')
        
        jobs[job_id]['video_title'] = video_title
        
        # Detect viral moments
        moments = detect_viral_moments(transcript, duration)
        
        if not moments:
            raise Exception("No viral moments detected")
        
        jobs[job_id]['status'] = 'creating_clips'
        jobs[job_id]['total_clips'] = len(moments)
        jobs[job_id]['progress'] = 40
        
        # Create output folder for this job
        output_folder = os.path.join(OUTPUT_FOLDER, job_id)
        os.makedirs(output_folder, exist_ok=True)
        
        # Create each clip
        created_clips = []
        for idx, moment in enumerate(moments, 1):
            output_filename = f"clip_{idx}.mp4"
            output_path = os.path.join(output_folder, output_filename)
            
            success = create_clip(
                video_path,
                moment['start'],
                moment['end'],
                output_path,
                transcript
            )
            
            if success:
                file_size = os.path.getsize(output_path) / (1024 * 1024)
                created_clips.append({
                    'filename': output_filename,
                    'duration': int(moment['end'] - moment['start']),
                    'size_mb': round(file_size, 1),
                    'preview_text': moment.get('text', '')[:80]
                })
            
            # Update progress
            progress = 40 + int((idx / len(moments)) * 50)
            jobs[job_id]['progress'] = progress
            jobs[job_id]['clips_created'] = idx
        
        # Complete
        jobs[job_id]['status'] = 'complete'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['clips'] = created_clips
        jobs[job_id]['completed_at'] = datetime.now().isoformat()
        
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
        print(f"Error processing job {job_id}: {e}")


@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/api/process', methods=['POST'])
def process_video():
    """Start processing a YouTube video"""
    data = request.json
    youtube_url = data.get('url', '').strip()
    
    if not youtube_url:
        return jsonify({'error': 'No URL provided'}), 400
    
    if 'youtube.com' not in youtube_url and 'youtu.be' not in youtube_url:
        return jsonify({'error': 'Invalid YouTube URL'}), 400
    
    # Create job
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'id': job_id,
        'url': youtube_url,
        'status': 'queued',
        'progress': 0,
        'created_at': datetime.now().isoformat()
    }
    
    # Start processing in background
    thread = threading.Thread(target=process_video_job, args=(job_id, youtube_url))
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>')
def get_status(job_id):
    """Get job status"""
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify(jobs[job_id])


@app.route('/api/download/<job_id>/<filename>')
def download_clip(job_id, filename):
    """Download a specific clip"""
    output_folder = os.path.join(OUTPUT_FOLDER, job_id)
    return send_from_directory(output_folder, filename, as_attachment=True)


@app.route('/api/download-all/<job_id>')
def download_all(job_id):
    """Download all clips as a zip"""
    import zipfile
    import io
    
    output_folder = os.path.join(OUTPUT_FOLDER, job_id)
    
    if not os.path.exists(output_folder):
        return jsonify({'error': 'Job not found'}), 404
    
    # Create zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename in os.listdir(output_folder):
            if filename.endswith('.mp4'):
                file_path = os.path.join(output_folder, filename)
                zip_file.write(file_path, filename)
    
    zip_buffer.seek(0)
    
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'tiktok_clips_{job_id}.zip'
    )


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🎬 TIKTOK CLIP MAKER - WEB VERSION")
    print("="*60)
    print("\n🌐 Server starting...")
    
    # Support cloud deployment (Render, Railway, etc.)
    port = int(os.environ.get('PORT', 5000))
    
    if port == 5000:
        print("📱 Open your browser to: http://localhost:5000")
    else:
        print(f"📱 Running on port: {port}")
    
    print("\n⚠️  Make sure FFmpeg and yt-dlp are installed!")
    print("="*60 + "\n")
    
    # Use debug=False for production
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
