"""The signed editor preserves and publishes ordered galleries, including retries."""

import json
import os
import re
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "APP_DATABASE_URL": "sqlite:///:memory:"}):
    from models import Base, MapTrivia, Trivia, TriviaCandidate
    from routers import line_admin
    from services.line_bot import make_editor_token


class SignedEditorGalleryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        secret = patch.dict(os.environ, {"CANDIDATE_EDITOR_SECRET": "gallery-editor-secret"})
        secret.start()
        self.addCleanup(secret.stop)
        session_patch = patch.object(line_admin, "SessionLocal", self.sessions)
        session_patch.start()
        self.addCleanup(session_patch.stop)
        app = FastAPI()
        app.include_router(line_admin.router)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.gallery = ["trivia/first.webp", "https://images.example.test/second.webp", "trivia/third.webp"]
        self.payload = {
            "title": "東京タワーの写真", "content": "東京タワーには正式な塗装色があります。",
            "source": "参考資料", "category": "地理",
            "add_to_normal": True, "add_to_map": True,
            "map_prefecture": "東京都", "map_address": "東京タワー",
            "map_latitude": 35.658581, "map_longitude": 139.745433, "map_radius": 500,
            "map_hint": "塔の色を見てみよう。",
        }

    def seed_candidate(self):
        with self.sessions() as db:
            item = TriviaCandidate(
                title="元のタイトル", content="元の本文", category="地理", status="pending",
                image_url=self.gallery[0], image_urls=self.gallery,
            )
            db.add(item)
            db.commit()
            return item.id

    def post(self, **changes):
        return self.client.post("/admin/candidates/new", json={
            **self.payload, "token": make_editor_token(0), **changes,
        })

    def put(self, candidate_id, **changes):
        return self.client.put(f"/admin/candidates/{candidate_id}/edit", json={
            **self.payload, "token": make_editor_token(candidate_id), **changes,
        })

    def test_new_gallery_publishes_to_both_destinations_in_order(self):
        result = self.post(image_urls=self.gallery, image_url="stale-cover.webp",
                           image_sources={self.gallery[1]: "写真提供：博物館"})
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            for model in (Trivia, MapTrivia):
                item = db.query(model).one()
                self.assertEqual(item.image_urls, self.gallery)
                self.assertEqual(item.image_url, self.gallery[0])
                self.assertEqual(item.source, "参考資料")
                self.assertEqual(item.image_sources, {self.gallery[1]: "写真提供：博物館"})
            self.assertEqual(db.query(MapTrivia).one().map_hint, self.payload["map_hint"])

    def test_existing_gallery_updates_and_preserves_candidate_review_history(self):
        candidate_id = self.seed_candidate()
        updated = list(reversed(self.gallery))
        result = self.put(candidate_id, image_urls=updated)
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            candidate = db.get(TriviaCandidate, candidate_id)
            self.assertEqual(candidate.image_urls, updated)
            self.assertEqual(candidate.image_url, updated[0])
            self.assertEqual(candidate.status, "approved")
            self.assertEqual(candidate.reviewed_by, "mobile-editor")
            self.assertIsNotNone(candidate.reviewed_at)
            self.assertEqual(candidate.published_trivia_id, result.json()["trivia_id"])
            self.assertEqual(db.query(MapTrivia).one().image_urls, updated)
        repeated = self.put(candidate_id, image_urls=updated)
        self.assertEqual(repeated.status_code, 409)

    def test_omitted_and_null_image_fields_preserve_existing_gallery(self):
        for changes, title, content in (
            ({}, "タコの心臓", "タコには心臓が三つあります。"),
            ({"image_urls": None}, "金星の自転", "金星は他の惑星と逆向きに自転しています。"),
        ):
            with self.subTest(changes=changes):
                # Different text permits a second independent publication.
                candidate_id = self.seed_candidate()
                result = self.put(candidate_id, title=title, content=content, **changes)
                self.assertEqual(result.status_code, 200, result.text)
                with self.sessions() as db:
                    candidate = db.get(TriviaCandidate, candidate_id)
                    item = db.get(Trivia, result.json()["trivia_id"])
                    self.assertEqual(candidate.image_urls, self.gallery)
                    self.assertEqual(item.image_urls, self.gallery)

    def test_legacy_cover_only_request_preserves_remaining_images(self):
        candidate_id = self.seed_candidate()
        result = self.put(candidate_id, image_url="trivia/replaced.webp")
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            item = db.get(Trivia, result.json()["trivia_id"])
            self.assertEqual(item.image_urls, ["trivia/replaced.webp", *self.gallery[1:]])

    def test_explicit_empty_gallery_clears_images_even_with_stale_legacy_cover(self):
        candidate_id = self.seed_candidate()
        result = self.put(candidate_id, image_urls=[], image_url=self.gallery[0])
        self.assertEqual(result.status_code, 200, result.text)
        with self.sessions() as db:
            for model in (Trivia, MapTrivia, TriviaCandidate):
                item = db.query(model).one()
                self.assertEqual(item.image_urls, [])
                self.assertFalse(item.image_url)

    def test_invalid_gallery_does_not_publish_or_change_review(self):
        candidate_id = self.seed_candidate()
        for gallery in ([f"trivia/{index}.webp" for index in range(11)], ["javascript:alert(1)"]):
            for endpoint in ("new", "existing"):
                with self.subTest(gallery=gallery, endpoint=endpoint):
                    response = self.post(image_urls=gallery) if endpoint == "new" else self.put(candidate_id, image_urls=gallery)
                    self.assertEqual(response.status_code, 400, response.text)
            with self.sessions() as db:
                self.assertEqual(db.query(Trivia).count(), 0)
                self.assertEqual(db.query(MapTrivia).count(), 0)
                candidate = db.get(TriviaCandidate, candidate_id)
                self.assertEqual(candidate.image_urls, self.gallery)
                self.assertEqual(candidate.status, "pending")
                self.assertIsNone(candidate.reviewed_at)

    def test_editor_renders_saved_gallery_and_multi_select_without_html_injection(self):
        candidate_id = self.seed_candidate()
        with self.sessions() as db:
            candidate = db.get(TriviaCandidate, candidate_id)
            candidate.image_urls = [*self.gallery, 'trivia/</textarea><script>alert("x")</script>.webp']
            db.commit()
        result = self.client.get(f"/admin/candidates/{candidate_id}/edit", params={"token": make_editor_token(candidate_id)})
        self.assertEqual(result.status_code, 200)
        self.assertIn('\n'.join(self.gallery), result.text)
        self.assertIn('type="file" accept="image/*" multiple', result.text)
        self.assertIn('id="image_gallery"', result.text)
        self.assertIn('id="image_count"', result.text)
        self.assertIn('1枚目を表紙', result.text)
        self.assertIn('&lt;/textarea&gt;&lt;script&gt;', result.text)
        self.assertNotIn('<script>alert("x")</script>', result.text)


class SignedEditorGalleryScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the browser script")
    def test_upload_and_save_retries_keep_order_and_never_repeat_successful_uploads(self):
        page = line_admin._editor_html(SimpleNamespace(
            id=0, title="題名", content="本文", explanation="", source="", category="その他",
            image_url="trivia/first.webp", image_urls=["trivia/first.webp"],
        ), "test-token", is_new=True)
        editor_script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
        harness = r'''
const assert=require("node:assert/strict"),vm=require("node:vm");
class Element {
 constructor(){this.value="";this.checked=false;this.listeners={};this.children=[];}
 addEventListener(name,listener){this.listeners[name]=listener;}
 append(...children){this.children.push(...children);}
 replaceChildren(){this.children=[];}
 setAttribute(){}
}
const elements={},ids=["title","content","explanation","source","category","image_urls","image_sources","image_file","image_gallery","image_count","message","add_to_normal","add_to_map","map_section","map_spot_id","map_address","map_prefecture","map_latitude","map_longitude","map_radius","map_hint"];
ids.forEach(id=>elements[id]=new Element());
Object.assign(elements.title,{value:"題名"});Object.assign(elements.content,{value:"本文"});
elements.image_urls.value="trivia/first.webp";elements.add_to_normal.checked=true;
elements.image_sources.value=JSON.stringify({"trivia/first.webp":"写真提供：博物館"});
const requests=[],responses=[];
class TestURL extends URL {}
TestURL.createObjectURL=file=>"blob:"+file.name;TestURL.revokeObjectURL=()=>{};
const context=vm.createContext({
 document:{getElementById:id=>elements[id],createElement:()=>new Element(),querySelectorAll:()=>Object.values(elements)},
 URL:TestURL,FormData:class {append(){}},window:{location:{pathname:"/admin/candidates/new"}},navigator:{},
 fetch:async(path,options)=>{requests.push({path,...options});const response=responses.shift();assert.ok(response,"Unexpected request");return {ok:response.ok,json:async()=>response.data};}
});
const run=script=>vm.runInContext(script,context);
run(EDITOR_SCRIPT);
(async()=>{
 // Reject excessive galleries before making any upload or publication request.
 elements.image_urls.value=Array.from({length:11},(_,index)=>`trivia/${index}.webp`).join("\n");
 elements.image_urls.listeners.input();await run("submitCandidate()");assert.equal(requests.length,0);
 elements.image_urls.value="trivia/first.webp";elements.image_urls.listeners.input();
 elements.image_file.listeners.change({target:{files:[
  {name:"one.jpg",size:100,lastModified:1,type:"image/jpeg"},
  {name:"two.jpg",size:200,lastModified:2,type:"image/jpeg"}
 ]}});
 run("moveImage(1,-1)");
 run("gallery[0].source='撮影：山田太郎'");
 responses.push({ok:true,data:{image_url:"trivia/upload-one.webp"}},{ok:false,data:{detail:"second upload failed"}});
 await run("submitCandidate()");
 assert.equal(requests.length,2);assert.equal(elements.image_urls.value,"trivia/upload-one.webp\ntrivia/first.webp");
 assert.equal(run("gallery.filter(item=>item.file).length"),1);
 responses.push({ok:true,data:{image_url:"trivia/upload-two.webp"}},{ok:false,data:{detail:"save failed"}});
 await run("submitCandidate()");assert.equal(requests.length,4);
 assert.deepEqual(JSON.parse(requests[3].body).image_urls,["trivia/upload-one.webp","trivia/first.webp","trivia/upload-two.webp"]);
 assert.equal(run("gallery.filter(item=>item.file).length"),0);
 responses.push({ok:true,data:{ok:true}});await run("submitCandidate()");
 assert.equal(requests.length,5);assert.equal(requests.filter(request=>request.path==="/admin/candidates/image").length,3);
 assert.deepEqual(JSON.parse(requests[4].body).image_urls,["trivia/upload-one.webp","trivia/first.webp","trivia/upload-two.webp"]);
 assert.deepEqual(JSON.parse(requests[4].body).image_sources,{"trivia/upload-one.webp":"撮影：山田太郎","trivia/first.webp":"写真提供：博物館"});
 assert.equal(elements.message.textContent,"登録しました。LINEへ戻ってください。");
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace("EDITOR_SCRIPT", json.dumps(editor_script))
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
