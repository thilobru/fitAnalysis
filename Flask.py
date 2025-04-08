# Import necessary libraries
from flask import Flask, request, jsonify
import fitparse
import gpxpy
import pandas as pd
import numpy as np
import plotly.graph_objs as go
import plotly.io as pio
import os

# Initialize Flask app
app = Flask(__name__)

# Route to display HTML form for file upload
@app.route('/')
def upload_form():
    return '''
    <!doctype html>
    <title>Upload a FIT or GPX file</title>
    <h1>Upload a FIT or GPX file</h1>
    <form method="post" action="/upload" enctype="multipart/form-data">
      <input type="file" name="file">
      <input type="submit" value="Upload">
    </form>
    '''

# Function to parse FIT file
def parse_fit_file(file_path):
    fitfile = fitparse.FitFile(file_path)
    data = {'timestamp': [], 'heart_rate': [], 'power': [], 'speed': [], 'latitude': [], 'longitude': []}
    
    for record in fitfile.get_messages('record'):
        for field in record:
            if field.name in data:
                data[field.name].append(field.value)
    
    return pd.DataFrame(data)

# Function to parse GPX file
def parse_gpx_file(file_path):
    with open(file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
        data = {'latitude': [], 'longitude': [], 'elevation': [], 'time': []}
        
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    data['latitude'].append(point.latitude)
                    data['longitude'].append(point.longitude)
                    data['elevation'].append(point.elevation)
                    data['time'].append(point.time)
                    
    return pd.DataFrame(data)

# Function to calculate basic metrics
def calculate_metrics(df):
    metrics = {}
    if 'speed' in df.columns:
        metrics['average_speed'] = df['speed'].mean() * 3.6  # m/s to km/h
    if 'heart_rate' in df.columns:
        metrics['average_heart_rate'] = df['heart_rate'].mean()
        metrics['max_heart_rate'] = df['heart_rate'].max()
    if 'power' in df.columns:
        metrics['average_power'] = df['power'].mean()
    if 'elevation' in df.columns:
        metrics['elevation_gain'] = df['elevation'].diff().clip(lower=0).sum()
    
    return metrics

# Function to create visualizations
def create_visualizations(df):
    figures = []
    if 'heart_rate' in df.columns:
        hr_fig = go.Figure()
        hr_fig.add_trace(go.Scatter(x=df.index, y=df['heart_rate'], mode='lines', name='Heart Rate'))
        hr_fig.update_layout(title='Heart Rate Over Time', xaxis_title='Time', yaxis_title='Heart Rate (bpm)')
        figures.append(pio.to_html(hr_fig, full_html=False))
    
    if 'speed' in df.columns:
        speed_fig = go.Figure()
        speed_fig.add_trace(go.Scatter(x=df.index, y=df['speed'] * 3.6, mode='lines', name='Speed'))  # m/s to km/h
        speed_fig.update_layout(title='Speed Over Time', xaxis_title='Time', yaxis_title='Speed (km/h)')
        figures.append(pio.to_html(speed_fig, full_html=False))
    
    return figures

# Route to upload and process file
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    # Save the file locally
    file_path = os.path.join('uploads', file.filename)
    file.save(file_path)
    
    # Determine file type and parse accordingly
    if file.filename.endswith('.fit'):
        df = parse_fit_file(file_path)
    elif file.filename.endswith('.gpx'):
        df = parse_gpx_file(file_path)
    else:
        return jsonify({'error': 'Unsupported file type'}), 400
    
    # Calculate metrics
    metrics = calculate_metrics(df)
    
    # Create visualizations
    figures = create_visualizations(df)
    
    # Clean up saved file
    os.remove(file_path)
    
    # Return metrics and visualizations
    return jsonify({'metrics': metrics, 'visualizations': figures})

# Run the app
if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=True, port=5000)
