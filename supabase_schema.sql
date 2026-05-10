-- ============================================================
-- MMA BRIDGE — Supabase Schema
-- Run this in the Supabase SQL Editor (supabase.com dashboard)
-- ============================================================

-- Events (shared between app and website)
CREATE TABLE IF NOT EXISTS events (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  type          TEXT DEFAULT 'FIGHT NIGHT',
  date          TEXT,
  iso_date      TEXT,
  location      TEXT,
  venue         TEXT,
  poster        TEXT,
  status        TEXT DEFAULT 'upcoming',
  main_card     JSONB DEFAULT '[]',
  prelims       JSONB DEFAULT '[]',
  early_prelims JSONB DEFAULT '[]',
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- User profiles (linked to Supabase auth.users)
CREATE TABLE IF NOT EXISTS user_profiles (
  id           UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  username     TEXT UNIQUE NOT NULL,
  email        TEXT,
  display_name TEXT,
  avatar_url   TEXT,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Ratings/reviews (shared — written by both app and website users)
CREATE TABLE IF NOT EXISTS ratings (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  event_id         TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  event_name       TEXT,
  hype_rating      REAL NOT NULL CHECK (hype_rating >= 1 AND hype_rating <= 5),
  fotn_prediction  TEXT,
  review_text      TEXT,
  user_id          UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  username         TEXT,
  display_name     TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Review likes
CREATE TABLE IF NOT EXISTS review_likes (
  id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  review_id  UUID NOT NULL REFERENCES ratings(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(review_id, user_id)
);

-- Review replies
CREATE TABLE IF NOT EXISTS review_replies (
  id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  review_id    UUID NOT NULL REFERENCES ratings(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL,
  display_name TEXT NOT NULL,
  reply_text   TEXT NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Reply likes
CREATE TABLE IF NOT EXISTS reply_likes (
  id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  reply_id   UUID NOT NULL REFERENCES review_replies(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(reply_id, user_id)
);

-- Challenges (app feature)
CREATE TABLE IF NOT EXISTS challenges (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  from_username TEXT NOT NULL,
  to_username   TEXT NOT NULL,
  event_id      TEXT,
  event_name    TEXT,
  status        TEXT DEFAULT 'pending',
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Row Level Security
-- ============================================================

ALTER TABLE events         ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles  ENABLE ROW LEVEL SECURITY;
ALTER TABLE ratings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_likes   ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE reply_likes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE challenges     ENABLE ROW LEVEL SECURITY;

-- Events: public read, service role write
CREATE POLICY "events_public_read"    ON events FOR SELECT USING (true);
CREATE POLICY "events_service_write"  ON events USING (auth.role() = 'service_role');

-- User profiles: public read, own write
CREATE POLICY "profiles_public_read"  ON user_profiles FOR SELECT USING (true);
CREATE POLICY "profiles_own_insert"   ON user_profiles FOR INSERT WITH CHECK (auth.uid() = id OR auth.role() = 'service_role');
CREATE POLICY "profiles_own_update"   ON user_profiles FOR UPDATE USING (auth.uid() = id OR auth.role() = 'service_role');

-- Ratings: public read, authenticated insert
CREATE POLICY "ratings_public_read"   ON ratings FOR SELECT USING (true);
CREATE POLICY "ratings_auth_insert"   ON ratings FOR INSERT WITH CHECK (auth.uid() IS NOT NULL OR auth.role() = 'service_role');
CREATE POLICY "ratings_own_update"    ON ratings FOR UPDATE USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- Review likes: public read, own manage
CREATE POLICY "likes_public_read"     ON review_likes FOR SELECT USING (true);
CREATE POLICY "likes_own_manage"      ON review_likes USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- Review replies: public read, authenticated insert
CREATE POLICY "replies_public_read"   ON review_replies FOR SELECT USING (true);
CREATE POLICY "replies_auth_insert"   ON review_replies FOR INSERT WITH CHECK (auth.uid() IS NOT NULL OR auth.role() = 'service_role');

-- Reply likes: public read, own manage
CREATE POLICY "reply_likes_read"      ON reply_likes FOR SELECT USING (true);
CREATE POLICY "reply_likes_manage"    ON reply_likes USING (auth.uid() = user_id OR auth.role() = 'service_role');

-- Challenges: public read, authenticated insert
CREATE POLICY "challenges_public_read" ON challenges FOR SELECT USING (true);
CREATE POLICY "challenges_auth_insert" ON challenges FOR INSERT WITH CHECK (auth.uid() IS NOT NULL OR auth.role() = 'service_role');
