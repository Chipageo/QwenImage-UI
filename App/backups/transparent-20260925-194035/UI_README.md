# Qwen UI — განახლებული განლაგება

ეს პაკეტი შეიცავს UI-ის ყველა საჭირო ფაილს. არ შეიცავს და არ ცვლის შენს ძველ `venv`, `test_qwen.py`, `.picasa.ini`, ფოტოებს ან მოდელის ფაილებს.

## დაყენება

1. შეგიძლიათ გაუშვათ `start-ui.cmd` პირდაპირ ამ ფოლდერიდან.
   - თუ `venv` არ არის ამ ფოლდერში, პროგრამა ავტომატურად მოძებნის მას `C:\Users\d.chipashvili\Qwen-Image-2.1\venv`-ში ან სხვა სტანდარტულ ადგილებში.
   - თუ ვერ იპოვის, ამოაგდებს Windows-ის საქაღალდის ასარჩევ ფანჯარას (Folder Picker), ერთხელ აირჩევთ Qwen/venv ფოლდერს და დაიმახსოვრებს.
   - ფოლდერის შესაცვლელად შეგიძლიათ გაუშვათ: `start-ui.cmd --select`.
2. პროგრამის ფანჯრის დახურვისას (X-ზე დაჭერისას) Python სერვერი ავტომატურად მომენტალურად გაითიშება.

```text
Qwen-Image-2.1/
  venv/                     ძველი — ადგილზე რჩება
  test_qwen.py              ძველი — ადგილზე რჩება
  .picasa.ini               ძველი — ადგილზე რჩება
  start-ui.cmd              ახალი გამშვები
  Generate images/          არსებული და ახალი გენერირებული ფოტოები
  App/
    ui/
      index.html
      style.css
      app.js
    launch_app.pyw
    qwen_backend.py
    ui_server.py
    Qwen Image Studio.vbs
    test_ui.py
    UI_README.md
    ui_logs/                შეიქმნება ავტომატურად
    ui_browser_profile/     შეიქმნება ავტომატურად
```

`Generate images` ფოლდერში არსებული ფოტოები შეინარჩუნე. ZIP-ში ეს ფოლდერი ცარიელია და ფოტოებს არ ანაცვლებს. თუ ძველი `ui_outputs` კიდევ არსებობს, მისი ფოტოები გადაიტანე `Generate images`-ში.

## ძველი UI დუბლიკატების დალაგება

პროგრამის წარმატებით გაშვების შემდეგ მთავარ ფოლდერში დარჩენილი ამავე სახელის ძველი UI ფაილები აღარ გამოიყენება: `launch_app.pyw`, `qwen_backend.py`, `ui_server.py`, `Qwen Image Studio.vbs`, `test_ui.py`, `UI_README.md`. მათი მოქმედი ვერსიები უკვე `App`-შია. მთავარ ფოლდერში `start-ui.cmd` დატოვე.

ძველი `ui_logs` და `ui_browser_profile` ფოლდერების შენარჩუნება შეგიძლია მათი `App`-ში გადატანით, მაგრამ მხოლოდ Qwen-ის ფანჯრისა და ფონური სერვერის დახურვის შემდეგ. ახალ პროფილთან ბრმად ნუ გააერთიანებ: პროგრამას მათი თავიდან შექმნაც შეუძლია. ZIP პირად ბრაუზერის პროფილსა და ძველ ჟურნალებს არ შეიცავს.

CMD-ის წამიერი გამოჩენის გარეშეც შეგიძლია გაუშვა `App\Qwen Image Studio.vbs`.

## შემოწმება

PowerShell-ში, მთავარი Qwen ფოლდერიდან:

```powershell
Set-Location .\App
..\venv\Scripts\python.exe -m unittest test_ui -v
```

სრული ფოლდერის სხვა ადგილას გადატანა იმავე კომპიუტერზე იყენებს ფარდობით მისამართებს. სხვა კომპიუტერზე გადასატანად არსებული საბაზისო Python, მოდელის ქეში და GPU გარემოც ცალკე მოსაწყობია.


## Performance & testing

Open the panel above the prompt. Settings apply to the next generation.

- CPU offload + Standard + KV cache ON + VAE tiling OFF is the baseline.
- Full GPU keeps all BF16 components on the GPU. The app rejects cards below 30 GiB because weights alone are approximately that size; larger GPUs still need working memory.
- Compiled standard and Compiled Flex Attention are experimental. They require Triton in the active Python environment and a working compatible compiler. Detecting the package does not guarantee successful compilation. If unavailable, options are disabled with an explanation. No packages are installed automatically.
- Changing memory or compute mode reloads the model. Initial compilation happens during generation and can take minutes or repeat for new shapes. Compiler failures clear the pipeline; select Standard to retry.
- KV cache OFF is a comparison option, usually slower. VAE tiling reduces image encode/decode memory and may affect speed and output slightly.
- Results show selected settings, setup time, preparation plus first step, remaining steps, finish time, and peak PyTorch allocated GPU memory. First-step time includes prompt processing, transfers, and any lazy compilation. It does not isolate those costs. Memory excludes other applications.
- Reuse restores the generated seed and performance settings. For fair tests use the same prompt, seed, reference images, size, and steps, and compare the second generation in each mode. Restore baseline only resets performance options.
- Restart Qwen Image Studio after installing this update. Existing image files and model weights are unchanged.

Tests: run `python -m unittest discover -s App -q` from the application root with its existing environment. Automated tests mock GPU execution; compilation speed and compatibility must be measured separately on the target system.
