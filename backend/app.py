
from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder='../E-Learning-Website-HTML-CSS-main')

# List of HTML files to add routes for
html_files = [
    'index.html',
    'about.html',
    'contact.html',
    'courses.html',
    'instructor.html',
    'login.html',
    'signup.html',
    'single.html',
    'team.html',
    'testimonial.html',
    'video.html',
    'chat-bot.html'
]

# Add a route for each HTML file
for html_file in html_files:
    route_path = '/' if html_file == 'index.html' else f'/{html_file}'
    def make_route(file):
        def route():
            return send_from_directory(app.static_folder, file)
        route.__name__ = f'route_{file.replace(".", "_")}'
        return route
    app.route(route_path)(make_route(html_file))

# Serve other static files (css, js, images, etc.)
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
