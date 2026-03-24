import os
import re

os.makedirs('templates', exist_ok=True)

try:
    with open('../server/public/detail.ejs', 'r', encoding='utf-8') as f:
        detail_content = f.read()

    # Replace EJS with Jinja2
    detail_content = re.sub(r'<% data\.forEach\(item => { %>', '{% for item in data %}', detail_content)
    detail_content = re.sub(r'<%= (item\.[a-zA-Z_]+) %>', r'{{ \1 }}', detail_content)
    detail_content = re.sub(r'<% }\); %>', '{% endfor %}', detail_content)

    with open('templates/detail.html', 'w', encoding='utf-8') as f:
        f.write(detail_content)
    print("Created templates/detail.html")
except Exception as e:
    print(f"Error copying detail: {e}")

try:
    with open('../server/public/graph.html', 'r', encoding='utf-8') as f:
        graph_content = f.read()

    graph_content = graph_content.replace('href="/public/detail.ejs"', 'href="/detail"')

    with open('templates/graph.html', 'w', encoding='utf-8') as f:
        f.write(graph_content)
    print("Created templates/graph.html")
except Exception as e:
    print(f"Error copying graph: {e}")

print("Template conversion complete.")
