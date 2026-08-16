from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, DateTime, Date, JSON, Float
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
    image_url = Column(String, nullable=True)
    hee_count = Column(Integer, default=0) # Added for "Hee" button
    embedding = Column(JSON, nullable=True) # Vector for similarity check


class MapTrivia(Base):
    __tablename__ = "map_trivia"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    explanation = Column(Text)
    source = Column(String)
    category = Column(String)
    image_url = Column(String, nullable=True)
    map_address = Column(String, nullable=False)
    map_prefecture = Column(String, nullable=False)
    map_latitude = Column(Float, nullable=False)
    map_longitude = Column(Float, nullable=False)
    map_radius = Column(Integer, nullable=False, default=500)
    map_hint = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    collection_id = Column(Integer, ForeignKey("collections.id"), index=True)
    trivia_id = Column(Integer, ForeignKey("trivia.id"), index=True)
    saved_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    collection = relationship("Collection", back_populates="items")
    trivia = relationship("Trivia")

class DailyAssignment(Base):
    __tablename__ = "daily_assignments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) # UUID from frontend
    date = Column(Date, index=True)
    trivia_id = Column(Integer, ForeignKey("trivia.id"), index=True)

    trivia = relationship("Trivia")

class TriviaCandidate(Base):
    __tablename__ = "trivia_candidates"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    content = Column(Text)
    explanation = Column(Text)
    source = Column(String)
    category = Column(String)
    image_url = Column(String, nullable=True)
    map_address = Column(String, nullable=True)
    map_prefecture = Column(String, nullable=True)
    map_latitude = Column(Float, nullable=True)
    map_longitude = Column(Float, nullable=True)
    map_radius = Column(Integer, nullable=True)
    map_hint = Column(String, nullable=True)
    status = Column(String, default="pending", index=True) # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    published_trivia_id = Column(Integer, ForeignKey("trivia.id"), nullable=True, unique=True)
    line_sent_at = Column(DateTime, nullable=True)
    embedding = Column(JSON, nullable=True)

    published_trivia = relationship("Trivia")


class DailyTriviaCollectionRun(Base):
    __tablename__ = "daily_trivia_collection_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(Date, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="running", index=True)
    requested_count = Column(Integer, nullable=False, default=10)
    collected_count = Column(Integer, nullable=False, default=0)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    web_search_calls = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class TriviaHee(Base):
    __tablename__ = "trivia_hees"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    trivia_id = Column(Integer, ForeignKey("trivia.id"), index=True)
    count = Column(Integer, default=0) # Max 10 per user per trivia
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trivia = relationship("Trivia")
