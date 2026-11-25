# 07b 口パク（`mode: ref2va`）の話者の指定と成功例

H3 で「声から口パクを直接作る」依頼を書く前に必ず読んでください。
H3 ランナーの運用で分かった「誰が歌うか」の指定方法、うまくいかなかった形、実際に採用された依頼の全文をまとめています。
依頼項目の仕様（`mode`・`audio`・`seconds` など）は `docs/H3受け渡し契約.md` を参照してください。

---

## 1. 話者（歌う人）の指定のしかた

**専用の項目もノードのピンもありません。プロンプトの文章で決めます。**

- ノード `MiniMaxH3ReferenceToVideo` の声の入口は `ref_audios.ref_audio_0` のみです（ランナーがつなぐのはこの 1 本だけ）。「この声は画面のこの人」と座標や番号で結ぶ口はありません。
- 人物に `(S1)`・`(S2)` … と名前を付けて**見た目と位置**で定義し、声の持ち主と口を合わせる相手を `(S1)` にします。

### 書き方（3 か所で同じ人を指す）
1. **`subject_definitions:` で人を定義する**：見た目（髪・服・持ち物）と位置（中央・左など）を具体的に書きます。
   - 歌う人：`(S1) is the young woman in the center: …`
   - 歌わない人：`(S2) is the man on the left: … (S2) does not sing.`（人数分、`(S3)`・`(S4)`… と並べる）
2. **声を `(S1)` に結ぶ**：
   - `<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's complete final audio track, (S1) sings a song.`
3. **`detailed_description:` で口を `(S1)` に合わせ、ほかの人は口を動かさないと書く**：
   - `The mouth of (S1) movements are precisely synchronized with the Japanese lyrics.`
   - `(S2) … keep their mouths closed and keep the expressions from <Picture 1>; they never sing or talk.`
   - 開始の絵で笑顔（口が開いている）の人は、「口を閉じる」より「**唇とあごを動かさない**」を主にします（無理に閉じさせると顔が変わるため）。

### 顔の参照画像を足すとき（`ref_images:`）
- `<Picture 2>` は `(S1)` の顔の参照だと書き、**`(S2)` の参照ではない**と明記します。
  - `<Picture 2> is not a reference for (S2); keep (S2)'s own face, hair, … exactly as in <Picture 1>.`
- 参照画像の背景・全身のポーズ・構図はまねない、とも明記します。
  - `Use <Picture 2> only for (S1)'s face and hairstyle identity; do not copy its gray backdrop, full-body pose or framing.`

### `prompt: auto` の場合
ランナーが自動組み立てするプロンプトは **1 人で歌う前提（`(S1)` 固定）** です。歌わない人が映るカットでは、プロンプトを英語で全文書きます。

### 実績
偽マリアの複数人カット 6 本（ドラムと 2 人、バンド 5 人の引き、2 人のアップなど）で、上の書き方により **`(S1)` だけが口パクしました**。
完成動画でもコマを並べたシートでも、ほかの人が歌っているコマは見当たりませんでした。**この書き方で、複数人のカットでも歌う人を選べます。**

---

## 2. うまくいかなかった形と、そこから分かったこと

### 失敗：1 本の声の中で 2 人が順番にしゃべる
- **条件**：2D アニメの絵、7.0 秒。TTS のせりふ 2 人分を 1 本の声に混ぜて渡し、プロンプトで「`(S1)` が 00:00.79〜04.06、`(S2)` が 00:04.57〜07.10 に話す、`(S3)` は話さない、同時に口を動かすのは 1 人だけ」と時刻つきで指定。設定は既定（20 step・`simple`・`ref_image_size: match`・顔の参照なし）。
- **結果**：**だめ**。モデルが音を写さずに作り直しました（出力音と渡した声の音量の形の相関が −0.21。成功カットは 0.999）。
  - 口はその作り直した音に合ってしまい、話者も時刻も効きませんでした（話さないはずの人が最初の 2 秒、しゃべるように口を動かした）。
  - 絵は崩れませんでした（明るさ −10%、彩度 −13%）。
- **分かったこと**：成功している形（1 本の声＝1 人が歌う／話す）から外れると効きません。**掛け合いは、1 人ずつの区間に分けて別々に作ります。**

### 掛け合いを 1 人ずつに分けたら通った
- **条件**：各カットを「前半＝1 人目だけの声」「後半＝2 人目だけの声（開始の絵＝前半の最後のコマ。色を元の絵に合わせ直す）」の 2 本に分割し、どちらも「`(S1)` だけがしゃべる」型で生成（2D アニメ、声 2.05〜4.45 秒、生成 73〜124 コマ、20 step・`simple`）。
- **結果**：18 本すべて失敗なし。**どのカットも `(S1)` だけがせりふの区間で口を動かしました。** 短い 73〜107 コマも通り、音の写り（相関）は 0.9 以上が 11 本でした。
- **だめだった 3 本の原因**：**声の途中に約 0.4 秒以上の無音がある**と、モデルが音を写さず言葉を遅らせて作り直しやすい傾向がありました（相関 −0.07〜0.29）。
  - 対策：声の中の無音は詰めるか、そこで区間を分けます。
- **口の形**：開始の絵で口が開いている人（笑顔・叫び・驚き）は、その口の形のまま止まります（閉じません）。

### 演技を大きく書くと、声の写りが落ちる
- **条件**：同じ 18 カットを、長いプロンプト（約 550〜600 語：ギャグアニメの演技の型＋キャラごとの秒ごとの動き＋言葉の区切りの時刻＋「無音では口を閉じる」）で作り直しました。
- **演技の変化**：
  - 動き（コマ間の差の平均）は前の版の約 2〜10 倍になり、白目・青ざめ・汗・涙の噴水・煙などの記号も出ました。
  - 一方、重ねた動き（高く掲げる・体が浮く）、小さな繰り返し（うなずき・跳ね）、背景の物の変化は弱いままでした。
- **声の写りの低下**：**大きく落ちました**（前の版は 0.70〜1.00。そのまま写ったのは 2 本のみで、ほかは 0.5〜1 秒遅れて写る／作り直し／後ろに余分な声が入る）。演技の記述が多いと、音を写すより演技を優先するとみられます。
- **無音の限界**：0.5 秒以上の無音は、時刻を書いても「口を閉じる」と書いても直りませんでした。**無音は声の側で詰めるか、区間を分ける必要があります。**
- **前後つながりの乱れ**：後半が前半の動きをやり直す（座った姿勢に戻る）、最初から引きの画になる、開始の絵と違う姿勢から始まる（プロンプトに「〜を取り出す」と書くと取り出す前に戻される）といった現象が起きました。
- **使い分けの目安**：
  - **口をきっちり合わせたいカット**：演技の書き込みを控えめにします（成功例のような「歌う・話す＋少しの動き」）。
  - **演技を見せたいカット**：口のずれを編集で吸収する前提にします。

### ⭐ アニメ（しゃべり）はアフレコにする
- **方針**：**アニメのしゃべりカットには `ref2va` を使いません。** `fl2va`（声を渡さない、1 カット 1 本）で絵を先に作り、セリフ（TTS）をあとで口に合わせます。**歌唱のカットだけ `ref2va`**（声と同時）を使います。
- **実績（アフレコ版 9 本）**：
  - 9 本すべてで「フリ → オチ」の流れが通りました（`ref2va` の演技版では、意味の分からない動きや前後のつながり切れが発生していた）。
  - 明るさは開始の絵の −3〜+5% に収まりました（`ref2va` は −9〜−11%）。
- **プロンプトに書くこと**：
  - 「フリ → オチ」の流れ、それぞれの動きの理由、話す人が口を動かす時刻
  - 「カメラは最初から最後まで同じ画角、ズームしない」
  - 「顔・肌の色を開始の絵のまま、顔に暗い影を落とさない」
- **注意**：
  - 動きと口は書いた時刻から 0.3〜1.5 秒ずれることがあります（遅れが多い）ため、セリフ側をずらして合わせます。
  - 派手な見せ場（爆発など）では、書いてもカメラが寄ることがあります。
  - 話さない人が反応で口を開けることがあります。

### できないこと・試していないこと
- **2 人がそれぞれ別の声で歌う（掛け合い・デュエット）**：ノード自体は声を 3 本まで（`<Audio 1〜3>`）受け取れますが、ランナーがつなぐのは 1 本のみです。「`(S1) sings <Audio 1>, (S2) sings <Audio 2>`」の形で書けそうですが未検証です。
- **顔がとても小さい引きの画**（5 人の引きなど）：口が甘くなりやすいため、歌う人のマイクを唇の下に持たせ、口が見えるように書きます。

---

## 3. 成功例

### 評価
- 最初の 1 本（1 人のアップ）で口パクは申し分なく、マイクが口の下に来て唇が見えたまま歌いました（前のやり方ではマイクが口元にあると崩れていた）。これを受け、マイクを持って歌う 13 カットをすべてこの形にしました。
- ただし 1 本目では顔が少しつぶれて見えたため、2 本目で**顔の対策**（下の 5 つ）を追加しました。13 カットはすべてこの対策入りで作り直して採用しています。
- **画質の注意**：`ref2va` は硬く暗い印象で映像の表現も少し落ちます（同じ開始の絵で比べると、明るさが約 8〜13% 低く彩度も少し低い）。**口パクが不要なカットは `fl2va` で依頼**し、`ref2va` のカットは取り込む際に明るさと彩度を合わせる前提にします（11）。

### 顔の対策（13 カットすべてに適用）
1. `ref_image_size: max`（開始の絵との一致度が上がる。やや遅い）
2. `ref_images:` に顔の参照（そのキャラの立ち絵）＝ `<Picture 2>` を指定
3. `subject_definitions` に、開始の絵を見て書いた**顔の言葉**（目・まつ毛・メイク・鼻・唇・あご・肌）を追加
4. `fl2va` のときのプロンプトの **Look の行を一字一句そのまま**入れる（画風が落ちると顔のかわいさも落ちるため）
5. `scheduler: beta`、`steps: 25`

### 例 1：1 人のアップ（採用）
- **設定**：横 1344×768、出力 4.00 秒（96 コマ）、生成 124 コマ（前の空き 12 コマを捨てる）、`steps: 25`・`beta`、LoRA なし。生成時間は約 14 分（A100）。
- **時間軸**：曲の 68.50〜72.50 秒、歌は 69.03〜72.53 秒。プロンプトの時刻は**生成の時間軸（前の空き 0.5 秒込み）**で、歌い出し `00:01.030`、歌い終わり `00:04.530`。
- ファイルパス（`image`・`ref_images`・`audio`）は例です。自分の置き場に合わせてください。

```yaml
project: my_mv
id: c18_ref2va_v2
mode: ref2va
image: "<入力のフォルダ>/c18_first.png"
ref_images:
  - "<立ち絵のフォルダ>/singer.png"
ref_image_size: max
scheduler: beta
steps: 25
audio: "<曲のフォルダ>/song (Vocals).wav"
audio_start: 68.50
audio_seconds: 4.00
seconds: 4.00
lyrics: "私たちの中で生き続ける"
sing_start: 69.03
sing_end: 72.53
prompt: |
  subject_definitions:
  <Picture 1> is the exact first frame of [Shot 1] at 00:00.000.
  <Picture 2> is the identity reference of (S1): her face, eyes, makeup and hairstyle must match <Picture 2> and <Picture 1> exactly.
  (S1) is the young woman in the center: long wavy silver-lavender twin tails streaked hot pink and purple, pink and black bows with gold charms, dangling pink heart earrings, rhinestone choker and gold chains, hot pink hoodie, long pink decorated nails, holding a rhinestone pink microphone with a pink satin bow and a heart jewel close to her mouth. Her face: a beautiful idol-like gyaru face with delicate features, large almond-shaped light-brown eyes with long curled lashes, sharp black winged eyeliner and pink-tinted eye makeup, softly lifted emotional brows, a small nose, full glossy pink lips, a soft slim jawline, flawless porcelain skin.
  <Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's complete final audio track, (S1) sings a song.

  summary:
  A frontal close-up of (S1) singing an emotional, aching line into her microphone on a small pink idol-concert stage, her band blurred behind her.

  retention_analysis:
  Keep (S1)'s face, makeup, hairstyle, bows, earrings, choker, chains, hoodie, nails and the microphone exactly as in <Picture 1>, matching the identity reference <Picture 2>. Use <Picture 2> only for (S1)'s face and hairstyle identity; do not copy its gray backdrop, full-body pose or framing. Keep the blurred band members (a guitarist on the left, a long-haired keyboardist and a blue-haired guitarist on the right) and the pink neon hearts in the background.

  detailed_description:
  [Shot 1] The shot begins from <Picture 1> as the exact first frame at 00:00.000.
  <Audio 1> is the Japanese song with the lyrics <d>[Japanese]"私たちの中で生き続ける"</d>. The mouth of (S1) movements are precisely synchronized with the Japanese lyrics.
  From 00:00.000 to 00:01.030 (S1) breathes in softly with her lips slightly parted, eyes half closed, preparing to sing; her mouth stays still.
  From 00:01.030 to 00:04.530 (S1) sings the line with clear, natural Japanese mouth shapes for every syllable, singing just behind the microphone so her lips stay visible above it; her brows lift with emotion, her eyes glisten, and her head sways gently.
  After 00:04.530 she closes her mouth softly and holds the feeling.
  The hand holding the microphone stays steady and keeps five fingers; the microphone never covers her lips.
  Camera: static frontal close-up at eye level with a very slight handheld sway; no zoom.
  Lighting: hot pink stage light on her face, blue and magenta bokeh behind, soft bloom on the rhinestones.
  Look: vivid highlights of fluorescent pink, crimson, goldfish orange and deep black; dreamcore lavender and mint haze midtones. 35mm film grain, natural skin texture, soft bloom, shallow depth of field.
  Do not add any new text, captions, logos or watermarks.

  overall_soundscape:
  <Audio 1> only, copied exactly as the complete final audio track. No additional speech, ambience, crowd noise, instrument sound, or sound effects.

  non_diegetic_music:
  <Audio 1> only.
orientation: landscape
seed: 20261193
```

> 顔の対策を入れる前の 1 本目との違いは上の 5 点のみです（1 本目は `ref_images` なし・`ref_image_size: match`・`steps: 20`・`simple`・顔の言葉なし・Look が短い）。

### 例 2：5 人の引きで 1 人だけ歌う（採用）
- **時間軸**：曲の 64.80 秒から 3.70 秒、歌は 65.13〜67.965 秒（生成の時間軸で `00:00.830`〜`00:03.665`）。設定は例 1 と同じ顔の対策つき。
- **話者の指定に関わる部分**（その他は例 1 と同じ構成）：

```text
subject_definitions:
<Picture 1> is the exact first frame of [Shot 1] at 00:00.000.
<Picture 2> is the identity reference of (S1): her face, eyes, makeup and hairstyle must match <Picture 2> and <Picture 1> exactly.
(S1) is the young woman in the center of the five-piece band: … She sings with her eyes closed into a rhinestone pink microphone with a pink pom-pom held close to her mouth. Her face: …
(S2) is the drummer at far left: curly brown hair, black T-shirt, smiling with closed eyes. (S3) is the bassist on the left: long wavy silver-white hair, grey shirt, brown-grey vest, orange bolo tie, white bass. (S4) is the keytar player on the right: long straight silver hair, grey three-piece suit, red tie, pink keytar. (S5) is the guitarist at far right: blue bob, blue hoodie with green cuffs, white shirt and dark tie, blue guitar. (S2), (S3), (S4) and (S5) do not sing.
<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's complete final audio track, (S1) sings a song.

detailed_description:
…
From 00:00.830 to 00:03.665 (S1) sings the line with clear, natural Japanese mouth shapes, eyes closed, with a gentle emotional sway; the microphone stays just below her lower lip so her lips remain visible.
After 00:03.665 until the end of the shot she closes her mouth softly and holds the feeling, swaying gently; her mouth stays closed.
(S2) drums, (S3) plucks the bass, (S4) presses the keytar keys, (S5) strums the guitar, all with small bobbing moves; the four men keep their mouths closed and keep the expressions from <Picture 1>; they never sing or talk.
Camera: very slow push-in, all five stay in frame.
```

### 例 3：2 人のアップで 1 人だけ歌う（採用）
話者の指定に関わる行：

```text
(S2) is the man on the left: long wavy silver-white hair, a grey shirt, a brown-grey vest, an orange flower bolo tie, a blank, expressionless face with his eyes glancing sideways toward her. (S2) does not sing.
… Use <Picture 2> only for (S1)'s face and hairstyle identity; do not copy its gray backdrop, full-body pose or framing. <Picture 2> is not a reference for (S2); keep (S2)'s own face, hair, shirt, vest and bolo tie exactly as in <Picture 1>. …
(S2) stays expressionless the whole time; his lips stay closed and still, he never sings or speaks; only his eyes glance toward her.
```

---

## 4. コツのまとめ（成功例から）
- **プロンプト構成**：**英語**で、`subject_definitions`／`summary`／`retention_analysis`／`detailed_description`／`overall_soundscape`／`non_diegetic_music` の 6 節にします。歌詞は `<d>[Japanese]"…"</d>` 形式で書きます。
- **時刻と無音区間**：時刻は**生成の時間軸**（ランナーが先頭に 0.5 秒の無音を足すため、`曲の秒 − audio_start ＋ 0.5`）で書きます。歌い出しの前と歌い終わりの後に「口を動かさない」区間を明記します（長い無音があると勝手にしゃべり出すため）。
- **マイクと手**：マイクを持って歌う場合は「マイクは唇の下、唇は見えたまま」「指は 5 本」と書きます。
- **入力音声**：ボーカルだけのステム（伴奏なし）を渡します。歌い出しの前に小さな声が入っていても、息づかいに見える程度で、問題ありませんでした。
- **出力音声の扱い**：出力の音はモデルが作り直すため、作品では元の音に差し替えます。確認時も元のボーカルを付けた動画で確かめます。
- **モデルの使い分け**：画がきれいなのは `fl2va` です。口パクが必要なカットだけ `ref2va` を使います。
