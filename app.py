from flask import Flask, request, jsonify
import os
import traceback
from dotenv import load_dotenv
from github import Github
from groq import Groq
import requests

load_dotenv()

app = Flask(__name__)

# Učitaj environment varijable
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
CLICKUP_TOKEN = os.getenv('CLICKUP_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

def get_commit_details(repo, commit_sha):
    """Dobavi detalje commita sa GitHub-a"""
    try:
        g = Github(GITHUB_TOKEN)
        repository = g.get_repo(repo)
        commit = repository.get_commit(commit_sha)
       
        # Skupi sve promene
        files_changed = []
        for file in commit.files:
            files_changed.append({
                'filename': file.filename,
                'status': file.status,  # added, modified, removed
                'additions': file.additions,
                'deletions': file.deletions,
                'patch': file.patch if hasattr(file, 'patch') else None
            })
       
        return {
            'sha': commit.sha[:7],  # Skraceni SHA
            'message': commit.commit.message,
            'author': commit.commit.author.name,
            'date': commit.commit.author.date.strftime('%Y-%m-%d %H:%M'),
            'files': files_changed,
            'stats': {
                'additions': commit.stats.additions,
                'deletions': commit.stats.deletions,
                'total': commit.stats.total
            }
        }
    except Exception as e:
        print(f"Greska pri dobavljanju commita: {e}")
        return None


def analyze_with_ai(commit_details):
    """Pošalji commit AI-ju na analizu"""
    try:
        # Napravi prompt za AI
        files_summary = "\n".join([
            f"- {f['filename']} ({f['status']}, +{f['additions']}/-{f['deletions']})"
            for f in commit_details['files'][:10]  # Max 10 fajlova
        ])
       
        # Dodaj patch info za male promene
        code_changes = ""
        for f in commit_details['files'][:3]:  # Samo prva 3 fajla
            if f['patch'] and len(f['patch']) < 500:  # Samo mali patch-evi
                code_changes += f"\n\n{f['filename']}:\n{f['patch']}"
       
        prompt = f"""Analiziraj ovaj Git commit i napiši kratak update za razvojni tim.

**Commit info:**
- Autor: {commit_details['author']}
- Poruka: {commit_details['message']}
- Datum: {commit_details['date']}
- SHA: {commit_details['sha']}

**Statistika:**
- Ukupno promena: {commit_details['stats']['total']} linija
- Dodato: {commit_details['stats']['additions']} linija
- Obrisano: {commit_details['stats']['deletions']} linija

**Promenjeni fajlovi:**
{files_summary}

**Promene u kodu:**
{code_changes[:1000]}

Napiši update u sledecem formatu:

**Kratak opis (2 rečenice):**
[Šta je urađeno i zašto]

**Izmenjeni fajlovi:**
[Lista glavnih fajlova sa objašnjenjem šta je promenjeno]

**Nove/Izmenjene funkcionalnosti:**
[Lista ključnih metoda/funkcija sa kratkim opisom]

Budi koncizan i fokusiraj se na BITNE promene za tim."""

        # Pozovi Groq AI
        client = Groq(api_key=GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Ti si pomoćnik za razvojne timove koji piše jasne i koncizne Git commit summaries na srpskom jeziku."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3,  # Manje kreativnosti, više preciznosti
            max_tokens=800
        )
       
        return chat_completion.choices[0].message.content
   
    except Exception as e:
        print(f"Greska pri AI analizi: {e}")
        return f"Greska pri analizi: {str(e)}"


def format_clickup_message(commit_details, ai_summary):
    """Formatira poruku za ClickUp karticu"""
    message = f""" **Git Push Update**

**Branch:** `{commit_details.get('branch', 'main')}`
**Commit:** `{commit_details['sha']}`
**Autor:** {commit_details['author']}
**Vreme:** {commit_details['date']}

---

{ai_summary}

---

📊 **Statistika:**
- ✅ Dodato: {commit_details['stats']['additions']} linija
- ❌ Obrisano: {commit_details['stats']['deletions']} linija
- 📝 Ukupno: {commit_details['stats']['total']} linija
- 📁 Fajlova: {len(commit_details['files'])}

**Commit poruka:** _{commit_details['message']}_
"""
    return message

def extract_task_id(branch_name, commit_message):
    """Ekstraktuj ClickUp Task ID iz branch imena ili commit poruke"""
    import re

    pattern = r'/([a-z0-9]{9})-'
   
    # Prvo probaj branch name
    for pattern in patterns:
        match = re.search(pattern, branch_name, re.IGNORECASE)
        if match:
            return match.group(1)
   
    # Ako nema u branch-u, probaj commit poruku
    for pattern in patterns:
        match = re.search(pattern, commit_message, re.IGNORECASE)
        if match:
            return match.group(1)
   
    print("Task ID nije pronađen u branch-u ni u commit poruci")
    return None


def find_clickup_task(task_id):
    """Pronađi ClickUp task po ID-u"""
    try:
        headers = {
            'Authorization': CLICKUP_TOKEN,
            'Content-Type': 'application/json'
        }
       
        # ClickUp API endpoint za dobijanje taska
        url = f'https://api.clickup.com/api/v2/task/{task_id}'
       
        response = requests.get(url, headers=headers)
       
        if response.status_code == 200:
            task = response.json()
            print(f"Task pronadjen: {task['name']}")
            return task
        elif response.status_code == 404:
            print(f"Task {task_id} ne postoji")
            return None
        else:
            print(f"Greska pri traženju taska: {response.status_code}")
            return None
   
    except Exception as e:
        print(f"Greska: {e}")
        return None


def post_to_clickup(task_id, message):
    """Dodaj komentar na ClickUp task karticu"""
    try:
        headers = {
            'Authorization': CLICKUP_TOKEN,
            'Content-Type': 'application/json'
        }
       
        # ClickUp API endpoint za dodavanje komentara
        url = f'https://api.clickup.com/api/v2/task/{task_id}/comment'
       
        payload = {
            'comment_text': message
        }
       
        response = requests.post(url, headers=headers, json=payload)
       
        if response.status_code == 200:
            comment = response.json()
            print(f"Komentar uspesno dodat na task {task_id}")
            return True
        else:
            print(f"Greska pri dodavanju komentara: {response.status_code}")
            print(f"Response: {response.text}")
            return False
   
    except Exception as e:
        print(f"Greska: {e}")
        return False

@app.route('/')
def home():
    return " Git→ClickUp Bot radi!"

@app.route('/test')
def test_connections():
    results = {
        "github": "Not tested",
        "groq": "Not tested",
        "clickup": "Not tested"
    }
   
    # Test GitHub
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        results["github"] = f"Ulogovan kao: {user.login}"
    except Exception as e:
        results["github"] = f"Greska: {str(e)[:100]}"
   
    # Test Groq AI
    try:
        client = Groq(api_key=GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": "Reci samo 'radi!'",
                }
            ],
            model="llama-3.3-70b-versatile",
        )
       
        ai_response = chat_completion.choices[0].message.content
        results["groq"] = f"AI odgovorio: {ai_response[:50]}"
    except Exception as e:
        results["groq"] = f"Greska: {str(e)[:200]}"
   
    # Test ClickUp
    try:
        headers = {'Authorization': CLICKUP_TOKEN}
        r = requests.get('https://api.clickup.com/api/v2/user', headers=headers)
        if r.status_code == 200:
            data = r.json()
            results["clickup"] = f"Ulogovan kao: {data['user']['username']}"
        else:
            results["clickup"] = f"Status code: {r.status_code}"
    except Exception as e:
        results["clickup"] = f"Greska: {str(e)[:100]}"
   
    return jsonify(results)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Primi payload od GitHub-a
        payload = request.json
       
        # Proveri da li je push event
        if 'commits' not in payload:
            return jsonify({"status": "ignored", "reason": "Not a push event"}), 200
       
        print("\n" + "="*60)
        print("NOVI GITHUB PUSH PRIMLJEN!")
        print("="*60)
       
        # Informacije o push-u
        repo_name = payload['repository']['full_name']
        branch = payload['ref'].split('/')[-1]  # refs/heads/main -> main
        pusher = payload['pusher']['name']
       
        print(f"Repo: {repo_name}")
        print(f"Branch: {branch}")
        print(f"Pusher: {pusher}")
        print(f"Broj commit-ova: {len(payload['commits'])}")
       
        # Obradi svaki commit
        for commit_data in payload['commits']:
            commit_sha = commit_data['id']
            commit_msg = commit_data['message']
           
            print(f"\nObrađujem commit: {commit_sha[:7]} - {commit_msg[:50]}...")
           
            # Dobavi detaljne informacije
            commit_details = get_commit_details(repo_name, commit_sha)
           
            if not commit_details:
                print("Ne mogu dobaviti detalje commita")
                continue
           
            # Dodaj branch info
            commit_details['branch'] = branch
           
            print(f"Dobavljeno: {len(commit_details['files'])} fajlova")
           
            # Pošalji AI-ju na analizu
            print("Šaljem AI-ju na analizu...")
            ai_summary = analyze_with_ai(commit_details)
            print("AI analiza završena!")
           
            # Formatiraj poruku
            final_message = format_clickup_message(commit_details, ai_summary)
           
            # Za sada samo printuj (ClickUp integracija dolazi u CHECKPOINT 3)
            print("\n" + "="*60)
            print("FORMATIRANA PORUKA ZA CLICKUP:")
            print("="*60)
            print(final_message)
            print("="*60 + "\n")

            task_id = extract_task_id(branch, commit_msg)

            if task_id:
                print(f"Pronadjen Task ID: {task_id}")
            
                # Proveri da li task postoji
                task = find_clickup_task(task_id)
            
                if task:
                    # Pošalji komentar
                    success = post_to_clickup(task_id, final_message)
                
                    if success:
                        print(f"Update poslat na ClickUp karticu '{task['name']}'")
                    else:
                        print("Nije uspelo slanje na ClickUp")
                else:
                    print(f"Task {task_id} ne postoji ili nemas pristup")
            else:
                print("Task ID nije pronađen - komentar neće biti dodat na ClickUp")
                print(f"Koristi branch naming: feature/CU-taskid ili commit: [CU-taskid]")
    
        return jsonify({"status": "success", "processed": len(payload['commits'])}), 200

    except Exception as e:
        print(f"Greska u webhook handler-u: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)