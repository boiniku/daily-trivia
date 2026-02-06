from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, DateTime, Date, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class Trivia(Base):
    __tablename__ = "trivia"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    explanation = Column(Text)
    source = Column(String)
    category = Column(String)
    embedding = Column(JSON, nullable=True) # Vector for similarity check

class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) # Added for user personalization
    title = Column(String, index=True)
    icon = Column(String, default="folder-outline")
    is_locked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    items = relationship("CollectionItem", back_populates="collection")

class CollectionItem(Base):
    __tablename__ = "collection_items"

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id"))
    trivia_id = Column(Integer, ForeignKey("trivia.id"))
    saved_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    collection = relationship("Collection", back_populates="items")
    trivia = relationship("Trivia")

class DailyAssignment(Base):
    __tablename__ = "daily_assignments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) # UUID from frontend
    date = Column(Date, index=True)
    trivia_id = Column(Integer, ForeignKey("trivia.id"))

    trivia = relationship("Trivia")

class TriviaCandidate(Base):
    __tablename__ = "trivia_candidates"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    content = Column(Text)
    explanation = Column(Text)
    source = Column(String)
    category = Column(String)
    status = Column(String, default="pending", index=True) # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    embedding = Column(JSON, nullable=True)
