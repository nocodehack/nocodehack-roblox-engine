# Roblox face library

Real classic Roblox Face decals (assets/faces/<id>_<slug>/face.png, 420x420 RGBA). Fetch: tools/face_fetch.py; QA: tools/face_qa.py -> sheet.jpg; test: tests/test_faces_lib.py.

Use in a story: cast `"face": "lib:<slug>"` or beat `"face": "lib:<slug>"` / `"emo:<emotion>"` / bare emotion not built in (`shock`, `cry`, `laugh`, `happy`, `evil`, ...; `emo:x#2` = next face of that emotion). `talk` flaps swap to the open-mouth partner when one exists (TALK column); faces without a partner do not flap. Every face blinks with its `_shut` twin. FACE FAMILIES (LEVEL 1): meta `family` = `classic` (thin-line / dot eyes) or `bigeye` (outlined eyes with whites and pupils, measured by tools/face_measure.py); a character wears one family for the whole Short (cast `face_family`, short.schema.md), talk partners of another family are not used.

Automatic picks (acting.face_pass, off with scene key `"auto_faces": false`): every face beat and talk line gets an exact face of the written emotion, chosen by intensity and never one of the character's last two; `lib:<slug>` written in a story is kept as is. Each meta.json carries `intensity` 0..1 (big beats take the highest of the emotion), `eyes` / `mouth` boxes, `mouth_open`, and `auto` (false = only by explicit `lib:`), written by `python tools/face_measure.py` (rerun after a fetch; curated overrides live in that file). Every measured face now talks (`_talk`: real partner, else a twin made from the mouth box) and blinks (`_shut`: eye band squashed); QA sheet: tools/face_twins_sheet.py.

| emotion | key | Roblox name | id | talk partner |
|---|---|---|---|---|
| angry | lib:angry_zombie | Angry Zombie | 173789114 | - |
| angry | lib:bad_dog | Bad Dog | 10678423 | lib:roar |
| angry | lib:furious_george | Furious George | 277950647 | lib:roar |
| angry | lib:grr | Grr! | 19398554 | - |
| angry | lib:i_am_not_amused | I Am Not Amused | 7131886 | lib:rawr |
| angry | lib:rawr | RAWR! | 7076224 | - |
| angry | lib:roar | ROAR!!! | 406001167 | - |
| confused | lib:sym5469 | :-/ | 7075469 | - |
| confused | lib:dizzy_face | Dizzy Face | 10907551 | - |
| confused | lib:hmmm | Hmmm... | 7076076 | - |
| confused | lib:huh | Huh? | 150182466 | - |
| confused | lib:o_o2 | O.o | 7074595 | - |
| confused | lib:o_o | O_o | 66330265 | - |
| confused | lib:skeptic | Skeptic | 31117267 | - |
| confused | lib:whatchoo_talkin_bout | Whatchoo Talkin Bout | 7075089 | - |
| cool | lib:chill | Chill | 7074764 | - |
| cool | lib:extreme | eXtreme | 10831454 | - |
| cry | lib:sadfaic | Sadfaic | 117522793 | - |
| cry | lib:whaaaaaa | WHAAAaaa! | 14127194 | - |
| disgust | lib:sym1035 | :/ | 15471035 | - |
| disgust | lib:sym4577 | >_< | 15324577 | - |
| disgust | lib:awkward_eyeroll | Awkward Eyeroll | 150182378 | - |
| disgust | lib:i_hate_noobs | I Hate Noobs | 14030577 | - |
| disgust | lib:not_amused | Not Amused | 13038375 | - |
| disgust | lib:not_amused_2_0 | Not Amused 2.0 | 406000958 | - |
| disgust | lib:sick_day | Sick Day | 26619096 | - |
| disgust | lib:stink_eye | Stink Eye | 416846143 | - |
| evil | lib:and_then_we_ll_take_over | And then we'll take over the world! | 12732366 | - |
| evil | lib:classic_vampire | Classic Vampire | 7074836 | - |
| evil | lib:it_s_go_time | It's Go Time! | 7506141 | - |
| evil | lib:meanie | Meanie | 9250643 | - |
| evil | lib:monster_face | Monster Face | 49045351 | - |
| evil | lib:monster_smile | Monster Smile | 398675917 | - |
| evil | lib:sinister | Sinister | 8329686 | - |
| evil | lib:slickfang | Slickfang | 7317765 | - |
| evil | lib:stitchface | Stitchface | 8329679 | - |
| evil | lib:vampire | Vampire | 29532363 | - |
| happy | lib:3 | :3 | 15432080 | - |
| happy | lib:sym1826 | :] | 18151826 | lib:happy_d |
| happy | lib:sym7393 | =) | 14817393 | - |
| happy | lib:braces | Braces | 30394484 | - |
| happy | lib:cheerful_hello | Cheerful Hello | 362051644 | - |
| happy | lib:fang | Fang | 7075142 | lib:cheerful_grin |
| happy | lib:freckles | Freckles | 12145366 | - |
| happy | lib:friendly_grin | Friendly Grin | 25321961 | - |
| happy | lib:friendly_smile | Friendly Smile | 616381207 | - |
| happy | lib:shiny_teeth | Shiny Teeth | 20722130 | - |
| happy | lib:silly_fun | Silly Fun | 7699174 | lib:cheerful_grin |
| happy | lib:smile | Smile | 144075659 | lib:joyful_smile |
| happy | lib:smiling_girl | Smiling Girl | 209994875 | lib:joyful_smile |
| happy | lib:the_winning_smile | The Winning Smile | 880469676 | lib:laughing_fun |
| happy | lib:wink_blink | Wink-Blink | 22828351 | lib:happy_wink |
| joy | lib:sym6173 | ^_^ | 15366173 | - |
| joy | lib:cheerful_grin | Cheerful Grin | 33321848 | - |
| joy | lib:glee | Glee | 7074729 | - |
| joy | lib:happy_d | Happy :D | 406000730 | - |
| joy | lib:joyful_smile | Joyful Smile | 209995366 | - |
| joy | lib:joyous_surprise | Joyous Surprise | 28999228 | - |
| joy | lib:singing | Singing | 66330310 | - |
| joy | lib:super_happy_joy | Super Happy Joy | 280988698 | - |
| joy | lib:super_super_happy_face | Super Super Happy Face | 494291269 | - |
| laugh | lib:awesome_face | Awesome Face | 30394850 | - |
| laugh | lib:epic_face | Epic Face | 42070576 | - |
| laugh | lib:laughing_fun | Laughing Fun | 226217449 | - |
| laugh | lib:roblox_madness_face | ROBLOX Madness Face | 130213380 | - |
| laugh | lib:so_funny | So Funny | 32058239 | - |
| laugh | lib:xd_2_0 | XD 2.0 | 406001052 | - |
| love | lib:i_wuv_u | I wuv u | 10907545 | - |
| love | lib:love | Love | 11611321 | - |
| neutral | lib:sym7848 | -_- | 15637848 | - |
| neutral | lib:chubs | Chubs | 7076110 | - |
| neutral | lib:not_sure_if | Not sure if... | 173789324 | - |
| neutral | lib:shhh | Shhh... | 7076159 | - |
| neutral | lib:silence | Silence | 10860397 | - |
| neutral | lib:stare | Stare | 8560971 | lib:o |
| sad | lib:sym0193 | :-[ | 15470193 | - |
| sad | lib:anguished | Anguished | 8560975 | - |
| sad | lib:big_sad_eyes | Big Sad Eyes | 391496223 | - |
| sad | lib:concerned | Concerned | 9250660 | - |
| sad | lib:existential_angst | Existential Angst | 7074814 | - |
| sad | lib:face_of_disappointment | Face of Disappointment | 209994270 | - |
| sad | lib:sad | Sad | 7699177 | lib:d |
| sad | lib:sniffles | Sniffles | 14516578 | - |
| sad | lib:you_ated_my_caik | You ated my caik! | 21635583 | - |
| scared | lib:hold_it_in | Hold It In | 2222771916 | - |
| scared | lib:squiggle_mouth | Squiggle Mouth | 25166274 | - |
| scared | lib:sweat_it_out | Sweat It Out | 20909103 | - |
| scared | lib:uh_oh | Uh Oh | 7074944 | - |
| sheepish | lib:awkward_grin | Awkward Grin | 150182501 | - |
| sheepish | lib:awkward | Awkward.... | 23932048 | - |
| sheepish | lib:blinky | Blinky | 7506135 | - |
| sheepish | lib:err | Err... | 20418658 | - |
| sheepish | lib:freckled_cheeks | Freckled Cheeks | 25556219 | - |
| sheepish | lib:good_intentioned | Good Intentioned | 7317793 | - |
| sheepish | lib:i_didn_t_eat_that_cookie | I Didn't Eat That Cookie | 116042990 | - |
| sheepish | lib:robot_smile | Robot Smile | 30265169 | - |
| sheepish | lib:whistle | Whistle | 22877700 | - |
| shock | lib:o | :-o | 7317773 | - |
| shock | lib:anime_surprise | Anime Surprise | 416846300 | - |
| shock | lib:d | D: | 14812981 | - |
| shock | lib:disbelief | Disbelief | 20337343 | - |
| shock | lib:surprise | Surprise! | 23261769 | - |
| silly | lib:sym1558 | $.$ | 10831558 | - |
| silly | lib:p | :P | 14861743 | - |
| silly | lib:blerg | Blerg! | 12777646 | - |
| silly | lib:classic_goof | Classic Goof | 7074661 | - |
| silly | lib:drool | Drool | 7074893 | - |
| silly | lib:goofball | Goofball | 27134344 | - |
| silly | lib:happy_wink | Happy Wink | 236399287 | - |
| silly | lib:hypnoface | Hypnoface | 10770436 | - |
| silly | lib:lazy_eye | Lazy Eye | 7075502 | - |
| silly | lib:playful_vampire | Playful Vampire | 2409285794 | - |
| silly | lib:prankster | Prankster | 20052135 | - |
| silly | lib:toothy_grin | Toothy Grin | 7075434 | - |
| silly | lib:yum | Yum! | 26019070 | - |
| sleepy | lib:bored | Bored | 66330106 | - |
| sleepy | lib:tired_face | Tired Face | 141728790 | lib:yaaawwn |
| sleepy | lib:yaaawwn | YAAAWWN. | 162068415 | - |
| sleepy | lib:yawn | Yawn | 20010377 | - |
| smug | lib:32 | >:3 | 15177601 | - |
| smug | lib:check_it | Check It | 7074786 | - |
| smug | lib:fearless | Fearless | 7074991 | - |
| smug | lib:heeeeeey | Heeeeeey... | 21635565 | - |
| smug | lib:just_trouble | Just Trouble | 244160766 | - |
| smug | lib:know_it_all_grin | Know-It-All Grin | 26424808 | - |
| smug | lib:mr_chuckles | Mr. Chuckles | 10907541 | - |
| smug | lib:mysterious | Mysterious | 7132035 | - |
| smug | lib:smug | Smug | 406001308 | lib:know_it_all_grin |
| smug | lib:sneaky_steve | Sneaky Steve | 823012694 | lib:know_it_all_grin |
| smug | lib:suspicious | Suspicious | 209994929 | - |
| smug | lib:up_to_something | Up To Something | 1016186364 | - |
| smug | lib:winky | Winky | 7074864 | - |
