# lapisroot — Redmi Note 15 Pro 5G 一時ルート (KernelSU LKM)

対象デバイス: **Redmi Note 15 Pro 5G**（コードネーム `lapis` / MediaTek **MT6878** Dimensity 7400-Ultra）

`init_boot` パーティションに **KernelSU の LKM**（Loadable Kernel Module）を注入して一時的に root を取るための Linux 用ツールです。カーネル本体は置き換えません。`stop` で元の `init_boot` をバイト単位で書き戻します。

---

## 先に知るべきこと（重要）

1. **ブートローダーのアンロックが必須です。**
   このツールはロック解除を回避するエクスプロイトではありません。`init_boot` を fastboot で書き込むため、BL がロックされている場合は何もできません。

2. **`fastboot boot` による完全 RAM 起動はできません。**
   `lapis` は Android 13 以降のレイアウト（generic ramdisk が `init_boot`）なので、`init_boot.img` にはカーネルがありません。したがって「再起動したら消える」タイプの RAM ブートは使えず、`init_boot` を書き換えて `stop` で戻す方式になります。

3. **root は `stop` するまで再起動後も残ります。**
   「一時」の意味は「`stop` で確実に元へ戻せる」ことです。KernelSU Manager の「一時アンインストール」を使えば、再起動までの間だけ root を無効化できます。

4. **同一ビルドの stock `init_boot.img` が必須です。**
   異なるビルドのイメージを書くと AVB / anti-rollback で起動不能になります。必ず現在のビルドの fastboot ROM から取得してください。

---

## 仕組み

KernelSU の `ksud boot-patch` は `init_boot.img` の ramdisk に対して次を行います。

- 元の `/init` を `/init.real` に退避
- `ksuinit` を `/init` として配置
- `kernelsu.ko`（KMI に一致する LKM）を追加
- `ksu_config` を追加

起動時に `ksuinit` が `kernelsu.ko` をロードし、KernelSU の `su` が使えるようになります。カーネル（`boot.img`）は無変更なので、MediaTek の vendor モジュールとの相性問題を避けられます。

---

## 必要なもの

- Linux PC（x86_64 または aarch64）
- `adb` / `fastboot`（Android Platform Tools）
- Python 3.10 以上
- ブートローダーがアンロック済みの `lapis`
- 現在のビルドと一致する fastboot ROM（`.tgz`）または `init_boot.img`
- デバイスの KMI（`adb` 接続時は `uname -r` から自動判定）

`lapis` のカーネルは Xiaomi の MediaTek BSP（`lapis-v-oss`）で、**`android14-6.1`** である可能性が高いです。自動判定できない場合は `--kmi android14-6.1` を指定してください。

---

## 使い方

### 1. デバイスと KMI の確認

```bash
python3 -m lapisroot detect
```

`kmi: android14-6.1` のように表示されれば OK です。`unauthorized` と出たら、端末の「USB デバッグを許可しますか？」を承認してください。

### 2. 実行計画の確認

```bash
python3 -m lapisroot plan --stock /path/to/init_boot.img
```

`route: ready` なら実行可能です。`route: locked` ならブートローダーのアンロックが先です。

### 3. 一時ルート開始

```bash
python3 -m lapisroot start \
  --stock /path/to/init_boot.img \
  --kmi android14-6.1 \
  --allow-shell
```

- `--stock` には `init_boot.img` 単体、展開済み fastboot ROM のディレクトリ、または ROM の `.tgz` / `.zip` を指定できます（アーカイブからは `init_boot.img` だけを展開します）。
- `--allow-shell` を付けると、`adb shell su` が Manager の承認ダイアログなしで通ります。付けない場合は端末上の KernelSU Manager で許可してください。
- 初回は KernelSU Manager の APK も自動でダウンロードし、`adb install` します（`--no-manager` で無効化）。
- 実行前に確認プロンプトが出ます。自動化する場合のみ `--yes`。

### 4. 状態確認

```bash
python3 -m lapisroot status
```

### 5. 元に戻す（一時ルート終了）

```bash
python3 -m lapisroot stop
```

ジャーナルに記録した stock `init_boot` を書き戻し、再起動します。これで root は消えます。

---

## うまくいかないとき

### ブートループした

fastboot に入り（電源長押し + Volume Down）、`lapisroot stop` を実行してください。それでもだめなら、stock イメージを直接書き戻します。

```bash
fastboot flash init_boot /path/to/init_boot.img
fastboot reboot
```

### KMI が違うと言われる / 起動するが root が効かない

`--lkm` でカーネルに一致する `kernelsu.ko` を指定してください。KernelSU 公式の LKM は KMI 世代（`android14-6.1` の後ろの数字）まで完全一致しないとロードに失敗することがあります。KernelSU Next / SukiSU Ultra の LKM も `--variant` と `--lkm` の組み合わせで利用できます。

```bash
python3 -m lapisroot start --stock init_boot.img --kmi android14-6.1 \
  --variant KernelSU-Next --lkm /path/to/aarch64_android14-6.1_kernelsu.ko
```

### ブートローダーがロックされている

1. Xiaomi Community（Global リージョン）で解除申請
2. 72 時間〜30 日のバインド待ち
3. Mi Unlock で解除（データ消去）

中国リージョン端末は公式解除の対象外です。商用の ADB アンロックサービスは存在しますが、本ツールは関与しません。

### MediaTek BROM / preloader を診断したい

```bash
python3 -m lapisroot brom probe
```

`mtkclient` が必要です。端末を電源オフにし、Volume Up（または Down）を押しながら USB 接続して preloader/BROM モードにしてください。

**このコマンドは読み取り専用です。** MT6878 は mtkclient 側の DA 対応がまだ不完全で、Xiaomi の preloader が DAA/SLA を要求する場合は書き込みできません。ロックされた BL のまま boot パーティションへ書き込むと AVB で起動不能になるため、本ツールは BROM 経由の書き込みを意図的に実装していません。

---

## 脆弱性の自動ハント

```bash
python3 -m lapisroot hunt
python3 -m lapisroot hunt --execute --yes
```

`hunt` は端末から patch level・カーネル・platform・SELinux・build tags を収集し、同梱の CVE カタログ（`lapisroot/data/android_lpe_catalog.json`）と照合します。

- 既知の公開 LPE がビルドに該当しない場合は、その旨を明示して終了します。エクスプロイトを捏造することはありません。
- **PoC は同梱していません。** `pocs/<CVE>/manifest.json`（または `run.sh`）を自分で置いたものだけを `--execute` で実行します。書式は `pocs/README.md` を参照。
- `--execute` は対話確認なしでは動きません。自動化する場合のみ `--yes`。
- `--json` で `state-dir/reports/` に実行レポートを保存します。
- カタログは `--catalog` で差し替え可能です。網羅的なデータベースではないため、必ず vendor の bulletin と突き合わせてください。

ロックされた BL のまま既知の LPE を探す場合の実用的な順序は、`hunt` → 該当なしなら `brom probe` → それでもだめなら BL アンロック、です。

---

## 制限・免責

- ブートローダーアンロックの回避、AVB の無効化、Play Integrity の偽装は行いません。
- 端末のデータ消失・文鎮化・保証喪失のリスクは利用者の責任です。
- 必ず現在のビルドと一致する stock イメージを使用してください。
- Xiaomi の HyperOS アップデート後は `init_boot` が変わるため、再度 stock を取り直して `start` し直す必要があります。

---

## 構成

```
lapisroot/
  adb.py        adb ラッパー
  fastboot.py   fastboot ラッパー
  device.py     機種判定・BL 状態・KMI 判定・ルーティング
  firmware.py   init_boot の探索・検証・アーカイブからの部分展開
  kernelsu.py   ksud の取得・KMI 判定・boot-patch 実行
  brom.py       mtkclient 診断（読み取り専用）
  workspace.py  ジャーナルと stock イメージのバックアップ
  temp.py       start / stop / status のオーケストレーション
  cli.py        コマンドライン
tests/          ユニットテスト
```

## 開発

```bash
python3 -m unittest discover -s tests -v
```

`ksud boot-patch` 自体の動作確認は、`mkbootimg` で作成した合成 `init_boot.img` に対して行えます。

```bash
python3 - <<'PY'
from pathlib import Path
from lapisroot import kernelsu
bundle = kernelsu.KsuBundle(version="local", ksud=Path("/path/to/ksud"))
print(kernelsu.patch(bundle, Path("init_boot.img"), Path("out"), kmi="android14-6.1"))
PY
```
