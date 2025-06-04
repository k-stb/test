from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import tempfile
import threading
import time
from werkzeug.utils import secure_filename
from pathlib import Path
import subprocess
import json

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB max file size

# Globale Variablen für Konvertierungs-Status
conversion_status = {}

# Unterstützte Formate
SUPPORTED_INPUT_FORMATS = {
    'video': ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.3gp'],
    'audio': ['.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.wma']
}

SUPPORTED_OUTPUT_FORMATS = {
    'mp3': {'ext': '.mp3', 'codec': 'mp3', 'name': 'MP3 - Hohe Kompatibilität'},
    'aac': {'ext': '.aac', 'codec': 'aac', 'name': 'AAC - Gute Qualität, klein'},
    'wav': {'ext': '.wav', 'codec': 'pcm_s16le', 'name': 'WAV - Verlustfrei, groß'},
    'ogg': {'ext': '.ogg', 'codec': 'libvorbis', 'name': 'OGG - Open Source'},
    'flac': {'ext': '.flac', 'codec': 'flac', 'name': 'FLAC - Verlustfrei komprimiert'},
    'm4a': {'ext': '.m4a', 'codec': 'aac', 'name': 'M4A - Apple Format'}
}

def check_ffmpeg():
    """Prüft ob FFmpeg verfügbar ist"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_media_info(file_path):
    """Holt Medien-Informationen mit FFprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except:
        return None

def convert_media_background(input_path, output_format, quality, task_id, original_filename):
    """Background-Konvertierung mit Fortschritts-Updates"""
    try:
        conversion_status[task_id] = {"status": "analyzing", "progress": 5}
        
        # Medien-Info abrufen
        media_info = get_media_info(input_path)
        if not media_info:
            raise Exception("Kann Medien-Informationen nicht lesen")
        
        # Dauer für Fortschrittsberechnung
        duration = float(media_info['format'].get('duration', 0))
        
        conversion_status[task_id] = {"status": "converting", "progress": 10}
        
        # Output-Pfad erstellen
        input_name = Path(original_filename).stem
        output_ext = SUPPORTED_OUTPUT_FORMATS[output_format]['ext']
        output_path = os.path.join(tempfile.gettempdir(), f"{input_name}_{task_id}{output_ext}")
        
        # FFmpeg-Befehl erstellen
        codec = SUPPORTED_OUTPUT_FORMATS[output_format]['codec']
        
        cmd = ['ffmpeg', '-i', input_path, '-vn']  # -vn = nur Audio
        
        # Qualitäts-Einstellungen
        if output_format == 'mp3':
            if quality == 'high':
                cmd.extend(['-b:a', '320k'])
            elif quality == 'medium':
                cmd.extend(['-b:a', '192k'])
            else:  # low
                cmd.extend(['-b:a', '128k'])
        elif output_format == 'aac':
            if quality == 'high':
                cmd.extend(['-b:a', '256k'])
            elif quality == 'medium':
                cmd.extend(['-b:a', '128k'])
            else:  # low
                cmd.extend(['-b:a', '96k'])
        elif output_format in ['wav', 'flac']:
            # Verlustfreie Formate - keine Bitraten-Einstellung
            pass
        else:
            # Standard-Qualität für andere Formate
            if quality == 'high':
                cmd.extend(['-q:a', '2'])
            elif quality == 'medium':
                cmd.extend(['-q:a', '5'])
            else:  # low
                cmd.extend(['-q:a', '8'])
        
        cmd.extend(['-c:a', codec, '-y', output_path])
        
        # Konvertierung starten mit Fortschritts-Tracking
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        # Fortschritt überwachen
        while True:
            output = process.stderr.readline()
            if output == '' and process.poll() is not None:
                break
            
            if output and duration > 0:
                # Fortschritt aus FFmpeg-Output extrahieren
                if 'time=' in output:
                    try:
                        time_str = output.split('time=')[1].split()[0]
                        current_seconds = time_to_seconds(time_str)
                        progress = min(90, int((current_seconds / duration) * 80) + 10)
                        conversion_status[task_id]["progress"] = progress
                    except:
                        pass
        
        # Warten auf Prozess-Ende
        process.wait()
        
        if process.returncode != 0:
            error_output = process.stderr.read()
            raise Exception(f"FFmpeg Fehler: {error_output}")
        
        conversion_status[task_id] = {
            "status": "completed", 
            "progress": 100,
            "output_path": output_path,
            "output_filename": f"{input_name}{output_ext}"
        }
        
    except Exception as e:
        conversion_status[task_id] = {
            "status": "error", 
            "progress": 0,
            "error": str(e)
        }

def time_to_seconds(time_str):
    """Konvertiert HH:MM:SS.ms zu Sekunden"""
    try:
        parts = time_str.split(':')
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except:
        return 0

@app.route('/')
def index():
    """Hauptseite"""
    ffmpeg_available = check_ffmpeg()
    return render_template('converter.html', ffmpeg_available=ffmpeg_available)

@app.route('/convert', methods=['POST'])
def convert_file():
    """Datei-Upload und Konvertierungs-Start"""
    try:
        if not check_ffmpeg():
            return jsonify({'error': 'FFmpeg ist nicht installiert. Bitte installieren Sie FFmpeg zuerst.'}), 400
        
        if 'media_file' not in request.files:
            return jsonify({'error': 'Keine Datei ausgewählt'}), 400
        
        file = request.files['media_file']
        if file.filename == '':
            return jsonify({'error': 'Keine Datei ausgewählt'}), 400
        
        output_format = request.form.get('output_format', 'mp3')
        quality = request.form.get('quality', 'medium')
        
        # Datei-Extension prüfen
        file_ext = Path(file.filename).suffix.lower()
        all_supported = SUPPORTED_INPUT_FORMATS['video'] + SUPPORTED_INPUT_FORMATS['audio']
        
        if file_ext not in all_supported:
            return jsonify({'error': f'Dateformat {file_ext} wird nicht unterstützt'}), 400
        
        # Sichere Datei speichern
        filename = secure_filename(file.filename)
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, filename)
        file.save(file_path)
        
        # Task ID generieren
        task_id = f"conv_{int(time.time() * 1000)}"
        
        # Background-Konvertierung starten
        thread = threading.Thread(
            target=convert_media_background,
            args=(file_path, output_format, quality, task_id, filename)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'task_id': task_id, 'status': 'started'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/status/<task_id>')
def get_conversion_status(task_id):
    """Konvertierungs-Fortschritt abfragen"""
    if task_id in conversion_status:
        return jsonify(conversion_status[task_id])
    else:
        return jsonify({'error': 'Task nicht gefunden'}), 404

@app.route('/download/<task_id>')
def download_converted_file(task_id):
    """Konvertierte Datei herunterladen"""
    if task_id not in conversion_status:
        return jsonify({'error': 'Task nicht gefunden'}), 404
    
    status = conversion_status[task_id]
    if status['status'] != 'completed':
        return jsonify({'error': 'Konvertierung noch nicht abgeschlossen'}), 400
    
    output_path = status['output_path']
    output_filename = status['output_filename']
    
    return send_file(
        output_path, 
        as_attachment=True, 
        download_name=output_filename
    )

@app.route('/supported-formats')
def supported_formats():
    """API-Endpoint für unterstützte Formate"""
    return jsonify({
        'input_formats': SUPPORTED_INPUT_FORMATS,
        'output_formats': SUPPORTED_OUTPUT_FORMATS
    })

if __name__ == '__main__':
    # Template-Ordner erstellen falls nicht vorhanden
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(template_dir):
        os.makedirs(template_dir)
    
    print("🎬 Video-zu-Audio-Konverter startet auf: http://localhost:5001")
    print("📁 Unterstützte Eingabe-Formate:")
    print("   Video: MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V, 3GP")
    print("   Audio: MP3, WAV, AAC, OGG, FLAC, M4A, WMA")
    print("🎵 Unterstützte Ausgabe-Formate: MP3, AAC, WAV, OGG, FLAC, M4A")
    print("\n⚠️  WICHTIG: FFmpeg muss installiert sein!")
    print("   Download: https://ffmpeg.org/download.html")
    print("\nDrücke Ctrl+C zum Beenden")
    
    app.run(debug=True, host='0.0.0.0', port=5001)