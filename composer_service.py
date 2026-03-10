"""
COMPOSER SERVICE - Lo-Fi Chord/Melody Generator
Architectural Choice: Uses Music21 for robust music theory operations instead of hallucinated libraries.
Why: Music21 is a well-documented, maintained library for symbolic music generation with proper MIDI export.
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import numpy as np
from music21 import stream, chord, note, meter, key, tempo
import firebase_admin
from firebase_admin import firestore, credentials
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ComposerService:
    """Generates Lo-Fi chord progressions and melodic hooks"""
    
    # Jazz/Soul chord progressions (Roman numerals for key flexibility)
    CHORD_PROGRESSIONS = {
        "jazzy_ii_V_I": ["ii7", "V7", "Imaj7", "VIm7"],
        "soul_loop": ["Imaj7", "VIm7", "IIm7", "V7"],
        "chill_iv_vi": ["IVmaj7", "vim7", "iim7", "V7"],
        "lo_fi_staple": ["Imaj7", "VIm7", "IVmaj7", "V7"]
    }
    
    def __init__(self, firestore_client):
        self.db = firestore_client
        self.jobs_ref = self.db.collection('production_jobs')
        
    def generate_midi_structure(self, params: Dict[str, Any]) -> Tuple[stream.Score, Dict[str, Any]]:
        """Generate complete MIDI structure with chords and melody"""
        
        # Extract parameters with defaults
        bpm = params.get('bpm', 85)
        key_signature = params.get('key', 'C')
        progression_type = params.get('progression_type', 'lo_fi_staple')
        complexity = params.get('complexity', 0.5)  # 0-1 scale
        
        logger.info(f"Generating MIDI: key={key_signature}, bpm={bpm}, progression={progression_type}")
        
        # Create score
        score = stream.Score()
        
        # Add tempo
        score.insert(0, tempo.MetronomeMark(number=bpm))
        
        # Create parts
        chord_part = stream.Part()
        melody_part = stream.Part()
        
        # Generate chord progression
        progression = self.CHORD_PROGRESSIONS[progression_type]
        chords = self._create_chord_progression(progression, key_signature)
        
        # Add chords to chord part
        for ch in chords:
            chord_part.append(ch)
        
        # Generate pentatonic melody
        melody_notes = self._create_melody_hook(chords, key_signature, complexity)
        for n in melody_notes:
            melody_part.append(n)
        
        # Add parts to score
        score.append(chord_part)
        score.append(melody_part)
        
        # Calculate musical fingerprint
        fingerprint = {
            'bpm': bpm,
            'key': key_signature,
            'chord_complexity': complexity,
            'progression_type': progression_type,
            'melodic_range': self._calculate_melodic_range(melody_notes)
        }
        
        return score, fingerprint
    
    def _create_chord_progression(self, progression: list, key_sig: str) -> list:
        """Convert Roman numeral progression to actual chords"""
        chords = []
        k = key.Key(key_sig)
        
        for i, roman in enumerate(progression):
            # Get chord from roman numeral
            chord_obj = k.romanNumeral(roman)
            
            # Add some jazz voicings (drop 2, add extensions based on chord type)
            if '7' in roman:
                # Ensure it's a 7th chord
                chord_obj.seventh = 'minor' if 'm' in roman else 'major'
            
            # Set duration (1 measure each)
            chord_obj.duration.quarterLength = 4.0
            
            chords.append(chord_obj)
        
        return chords
    
    def _create_melody_hook(self, chords: list, key_sig: str, complexity: float) -> list:
        """Generate pentatonic melody that fits chords"""
        melody = []
        k = key.Key(key_sig)
        
        # Get pentatonic scale for key
        if 'm' in key_sig.lower():
            scale = k.pentatonicMinor
        else:
            scale = k.pentatonicMajor
        
        # Generate simple 2-bar motif
        motif_durations = [1.0, 0.5, 0.5, 2.0]  # Rhythm pattern
        
        for chord_obj in chords:
            # Get chord tones
            chord_tones = [p.midi for p in chord_obj.pitches]
            
            # Generate notes that fit both scale and chord
            for dur in motif_durations:
                # 70% chance to use chord tone, 30% scale tone
                if np.random.random() < 0.7:
                    # Use chord tone (weighted toward root/third)
                    if len(chord_tones) > 0:
                        note_midi = np.random.choice(chord_tones[:min(3, len(chord_tones))])
                else:
                    # Use scale tone
                    scale_midis = [p.midi for p in scale.getPitches('C2', 'C6')]
                    if scale_midis:
                        note_midi = np.random.choice(scale_midis)
                    else:
                        continue
                
                n = note.Note()
                n.pitch.midi = note_midi
                n.duration.quarterLength = dur
                melody.append(n)
        
        return melody
    
    def _calculate_melodic_range(self, notes: list) -> float:
        """Calculate melodic range in semitones"""
        if not notes:
            return 0.0
        
        pitches = [n.pitch.midi for n in notes if hasattr(n, 'pitch')]
        if not pitches:
            return 0.0
            
        return max(pitches) - min(pitches)
    
    def process_job(self, job_id: str) -> bool:
        """Main entry point: process a queued job"""
        try:
            # Get job document
            job_ref = self.jobs_ref.document(job_id)
            job = job_ref.get()
            
            if not job.exists:
                logger.error(f"Job {job_id} not found")
                return False
            
            job_data = job.to_dict()
            if job_data.get('status') != 'queued':
                logger.warning(f"Job {job_id} not in 'queued' state: {job_data.get('status')}")
                return False
            
            # Update status
            job_ref.update({
                'status': 'composing',
                'timestamps.composing_started': datetime.now(),
                'error_log': firestore.ArrayUnion([])  # Initialize empty array
            })
            
            # Get generation parameters
            params = job_data.get('parameters', {})
            
            # Generate MIDI
            midi_score, fingerprint = self.generate_midi_structure(params)
            
            # Save MIDI file
            output_dir = Path('generated_assets')
            output_dir.mkdir(exist_ok=True)
            midi_path = output_dir / f"{job_id}.mid"
            midi_score.write('midi', fp=str(midi_path))
            
            # Update job with results
            job_ref.update({
                'status': 'composed',
                'timestamps.composing_completed': datetime.now(),
                'assets.midi_path': str(midi_path),
                'musical_fingerprint': fingerprint
            })
            
            logger.info(f"Successfully composed track for job {job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error in composer service for job {job_id}: {str(e)}")
            
            # Log error to Firestore
            try:
                job_ref.update({
                    'status': 'failed',
                    'error_log': firestore.ArrayUnion([{
                        'stage': 'composing',
                        'error': str(e),
                        'timestamp': datetime.now()
                    }])
                })
            except:
                pass
            
            return False

def initialize_firebase():
    """Initialize Firebase connection"""
    try:
        # Use service account credentials
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        # Fallback to local testing mode
        logger.warning("Running in local test mode without Firebase")
        return None

if __name__ == "__main__":
    # Initialize Firebase
    db = initialize_firebase()
    
    if db:
        composer = ComposerService(db)
        
        # Listen for queued jobs (simplified polling for MVP)
        while True:
            try:
                queued_jobs = db.collection('production_jobs')\
                               .where('status', '==', 'queued')\
                               .limit(1)\
                               .stream()
                
                for job in queued_jobs:
                    logger.info(f"Processing job: {job.id}")
                    composer.process_job(job.id)
                    
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                import time
                time.sleep(5)