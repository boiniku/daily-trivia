import json
import os
from datetime import datetime

# Placeholder for AI generation logic
def fetch_ai_trivia_candidates():
    # In a real scenario, this would call OpenAI API or similar
    print("AI is generating trivia candidates...")
    
    candidates = []
    for i in range(1, 11):
        candidates.append({
            "id": i,
            "title": f"雑学のタイトル候補 {i}",
            "content": f"これはAIが生成した {i} 番目の雑学の内容です。驚くべき事実が含まれています。",
            "explanation": f"詳細な解説がここに入ります。なぜそうなっているのか、背景知識など。",
            "source": "信頼できるソース",
            "category": "一般"
        })
    
    return candidates

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"candidates_{date_str}.json"
    
    candidates = fetch_ai_trivia_candidates()
    
    # Save to file for admin review
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    
    print(f"Generated {len(candidates)} candidates in {filename}")
    print("Please run approve_trivia.py to review and upload.")

if __name__ == "__main__":
    main()
