from database import engine, SessionLocal
from models import Base, Trivia

def init_db():
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # Check if data exists
    if db.query(Trivia).count() == 0:
        print("Seeding database with initial data...")
        seed_data = [
            Trivia(
                title="ハチミツの秘密", 
                content="ハチミツは腐らない食品として知られています。保存状態が良ければ、数千年前のハチミツでも食べることができると言われています。",
                explanation="ハチミツは糖度が極めて高く、水分活性が低いため、細菌が繁殖できません。また、過酸化水素を発生させる酵素も含んでいるため、強い殺菌作用があります。",
                source="National Geographic",
                category="食品科学"
            ),
            Trivia(
                title="タコの心臓", 
                content="タコには心臓が3つあります。全身に血液を送るためのメインの心臓と、エラに送るための2つの心臓です。",
                explanation="タコはエラ心臓と呼ばれる2つの心臓でエラに血液を送り、酸素を取り込みます。もう1つの主心臓が全身に血液を送り出します。",
                source="Scientific American",
                category="生物学"
            ),
            Trivia(
                title="バナナの木", 
                content="バナナは木ではなく、巨大なハーブ（草）の一種に分類されます。茎のように見える部分は葉が重なったものです。",
                explanation="バナナの「木」に見える部分は、実際には「偽茎」と呼ばれる葉の鞘が重なり合ったものです。",
                source="Botanical Gardens",
                category="植物学"
            ),
             Trivia(
                title="パンダの秘密", 
                content="パンダの指は実は6本（または7本）あると言われています。竹を掴むための突起が進化したものです。",
                explanation="通常の5本の指に加えて、手首の骨が変形してできた「第6の指（橈側種子骨）」があります。これにより竹を器用に掴むことができます。",
                source="Smithsonian Magazine",
                category="動物学"
            )
        ]
        
        db.add_all(seed_data)
        db.commit()
        print("Database initialized!")
    else:
        print("Database already contains data.")
    
    db.close()

if __name__ == "__main__":
    init_db()
