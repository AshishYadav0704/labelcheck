/* LabelCheck web app. Plain JavaScript, no build step.
   All server text is inserted with textContent (never innerHTML) because
   product names and ingredients come from photos and public data. */
(() => {
  "use strict";

  // ---------------------------------------------------------------- i18n
  const T = {
    en: {
      profile: "Profile", heroTitle: "Know what’s in your food before you buy it.",
      heroLede: "Photograph a pack, scan its barcode or paste its label. LabelCheck checks every ingredient against WHO and FSSAI standards and tells you, in plain words, what it means for you.",
      photoHint: "Ingredient list and nutrition table", barcodeHint: "Fastest for well-known brands",
      typeHint: "Paste from the pack or a shopping site", sampleTag: "Sample report",
      sampleVerdict: "Limit to an occasional treat", sampleServing: "One 70 g serving uses",
      sampleSalt: "Salt", sampleSatFat: "Saturated fat", sampleSugar: "Sugar",
      standardsLead: "Checked against public standards from", featuresTitle: "What the report tells you",
      f1t: "A clear score and warnings", f1d: "A 0–100 score and A–E grade, with the HIGH SUGAR, SALT and FAT warnings FSSAI has proposed for packs.",
      f2t: "Every additive explained", f2d: "Each INS number checked for its safe daily limit, cancer classification, FSSAI status and bans in other countries.",
      f3t: "What regular eating can do", f3d: "Health effects linked to eating it often, how strong the evidence is, and a short video of the long-term picture.",
      f4t: "Advice for you", f4d: "For diabetes, blood pressure, kidney disease, pregnancy, children, allergies and vegetarian, vegan or Jain diets.",
      f5t: "Better choices", f5d: "Higher-scoring products other shoppers found, plus easy swaps from an Indian kitchen.",
      f6t: "Your data stays yours", f6d: "LabelCheck doesn’t store your photos, and your health profile stays on your phone.",
      howTitle: "How it works", s1t: "Scan or type the label", s1d: "A photo, a barcode or pasted text.",
      s2t: "Check what we read", s2d: "Fix any number before the report is made.",
      s3t: "Read your report", s3d: "Score, warnings, risks and better options.",
      processing: "Processing", gradeAria: (g, s) => `Grade ${g}, ${s} out of 100`,
      photoLabel: "Photograph label", scanBarcode: "Scan barcode", recent: "Your recent checks", back: "Back",
      captureTitle: "Add photos of the label",
      captureLede: "For the best result, add the ingredient list and the nutrition table. Hold the phone flat and fill the frame with the text.",
      addPhoto: "Add a photo", photoLimit: "Up to 4 photos. You can check and correct what we read before the report.",
      checkFood: "Check this food", scanTitle: "Point at the barcode", scanHint: "Hold steady about 15 cm away.",
      typeBarcode: "Or type the number under the barcode", look: "Look up", workingHint: "This usually takes 5 to 15 seconds.",
      newCheck: "New check", share: "Share", profileTitle: "Make reports personal",
      profilePrivacy: "Saved only on this phone. It is sent with each check to tailor the advice and is never stored on our server.",
      ageGroup: "Who is eating it?", conditions: "Health conditions", allergies: "Allergies", cancel: "Cancel",
      saveProfile: "Save profile", footer: "General information, not medical advice. Product data partly from Open Food Facts (ODbL).",
      steps: ["Reading the label…", "Checking ingredients against WHO and FSSAI limits…", "Looking for better options…", "Writing your report…"],
      barcodeSteps: ["Looking up the barcode…", "Checking ingredients against WHO and FSSAI limits…", "Writing your report…"],
      whatItMeans: "What this means", perServing: "One serving uses",
      perServingNote: (who, size) => `Share of the daily limit for ${who}, per ${size} serving.`,
      noServing: "The pack doesn’t show a serving size, so here is 100 g compared with the daily limit.",
      nutrition: (u) => `Nutrition per 100 ${u}`, scoreHow: "How the score was worked out", ingredients: "What’s in it",
      additives: "Additives", noAdditives: "No additives found in the ingredient list.", flagsT: "Worth knowing",
      allergensT: "Contains", traces: "May contain", healthT: "Linked long-term effects",
      healthIntro: "These are linked with regular, excess intake. One packet does not cause disease.",
      noRisks: "No long-term concerns stood out for this product.",
      longTerm: "If you eat it regularly", howOften: "How often", forHowLong: "For how long", makeVideo: "Make video",
      videoMaking: "Making your video… about 5 seconds.", videoFailed: "The video couldn’t be made. Try again in a minute.",
      videoNote: "An illustration of general evidence, not a prediction for any one person.",
      alternatives: "Better choices", fromScans: "Scored higher on LabelCheck", fromOFF: "Nutri-Score A or B in India (Open Food Facts)",
      homeSwaps: "Easy swaps", dataQuality: "About this reading", sources: "Sources", forYou: "For you",
      suitable: "Looks fine for your profile", caution: "Be careful", notSuitable: "Not suitable for you",
      addProfile: "Add your health conditions or allergies to get personal advice.", setProfile: "Set up profile",
      linkCopied: "Link copied", nutriScore: "Nutri-Score", nova: "Processing level (NOVA)",
      freq: { 1: "Once a week", 3: "3 times a week", 7: "Every day", 14: "Twice a day" },
      yearsL: (y) => `${y} ${y === 1 ? "year" : "years"}`,
      level: { low: "Low", medium: "Medium", high: "High", unknown: "Not shown" },
      age: { child: "Child (4–12)", teen: "Teen", adult: "Adult", senior: "Senior (60+)" },
      cond: { diabetes: "Diabetes", hypertension: "High blood pressure", heart_disease: "Heart disease", kidney_disease: "Kidney disease",
        pregnancy: "Pregnant", pku: "PKU", gout: "Gout", asthma: "Asthma", thyroid_condition: "Thyroid condition", weight_loss: "Losing weight" },
      allergen: { gluten: "Gluten (wheat)", milk: "Milk", egg: "Egg", peanut: "Peanut", tree_nuts: "Tree nuts", soy: "Soy",
        fish: "Fish", crustacean: "Shellfish", sesame: "Sesame", mustard: "Mustard", sulphites: "Sulphites" },
      who: { child: "a child", teen: "a teenager", adult: "an adult", senior: "an older adult" },
      byAI: "Written by AI from the facts in this report.", byTemplate: "Standard summary.",
      nutrientNames: { energy_kcal: "Energy", fat_g: "Fat", saturated_fat_g: "Saturated fat", trans_fat_g: "Trans fat",
        carbohydrates_g: "Carbohydrates", sugars_g: "Sugars", added_sugars_g: "Added sugars", fiber_g: "Fibre", protein_g: "Protein",
        salt_g: "Salt", sodium_mg: "Sodium" },
      nutrition_pts: "Nutrition", processing_pts: "Processing", additive_pts: "Additives",
      adi: "Safe daily limit (ADI)", adiNone: "No numerical limit needed", iarc: "IARC group", fssai: "FSSAI",
      confidenceLow: "Some of the label was hard to read. Check the key numbers against the pack.",
      offline: "You’re offline. Connect to the internet to check a product.",
      labelOff: "Photo reading isn’t available on this server right now. You can type the label or scan a barcode.",
      shareText: "Food label check",
      tooMany: "You can add up to 4 photos.", needPhoto: "Add at least one photo of the label.",
      cameraBlocked: "Camera access is blocked. Allow it in your browser settings, or type the barcode below.",
      noCamera: "This device has no camera we can use. Type the barcode below.",
      scanning: "Scanning…", found: (c) => `Found ${c}`, perUnit: (u) => `per 100 ${u}`,
      evidence: { strong: "strong evidence", moderate: "moderate evidence", limited: "limited evidence" },
      readMore: "Read the source", ingredientList: "Ingredient list as read",
      notOnLabel: (x) => `Not on the label: ${x}.`, unknownCodes: (x) => `Codes not in our reference list yet: ${x}.`,
      typeLabel: "Type the label", textTitle: "Type or paste the label",
      textLede: "Copy the ingredient list and nutrition table from the pack or a shopping site. Include the line that starts with “Ingredients”.",
      productName: "Product name", brand: "Brand", labelText: "Label text", readLabel: "Read the label",
      textTooShort: "Paste a bit more of the label: at least the ingredient list or the nutrition table.",
      reviewTitle: "Check what we read",
      reviewLede: "Compare these with the pack and fix anything that’s wrong. Leave a box empty if it isn’t on the label.",
      readBy: { claude: "Read by AI (Claude).", gemini: "Read by AI (Gemini).", ocr: "Read with basic text recognition. Please check every number.",
        text: "Read from the text you entered.", open_food_facts: "From Open Food Facts, a public product database.", manual: "Entered by hand." },
      category: "Type of food", isDrink: "This is a drink (values per 100 ml)", servingSize: "Serving size",
      vegMark: "Veg / non-veg mark", vegMarkOpts: { "": "Not shown", veg: "Green (veg)", non_veg: "Brown (non-veg)" },
      nutritionPer: (u) => `Nutrition per 100 ${u}`, ingredientsField: "Ingredients",
      needSomething: "Add the nutrition values or the ingredient list first.",
      missingNutrition: "Some key nutrition values are empty, so the score will be less reliable.",
      editDetails: "Edit details", diet: "Diet",
      diets: { any: "No restriction", vegetarian: "Vegetarian (no egg)", eggetarian: "Vegetarian + egg", vegan: "Vegan", jain: "Jain" },
      readSteps: ["Reading the label…", "Finding the ingredient list…", "Reading the nutrition table…"],
      analyzeSteps: ["Checking ingredients against WHO and FSSAI limits…", "Looking for better options…", "Writing your report…"],
      videoUnsupported: "This browser can’t play the video here. Download it instead.", download: "Download video",
      reviewed: "You checked these values.", categories: null,
    },
    hi: {
      profile: "प्रोफ़ाइल", heroTitle: "ख़रीदने से पहले जानिए आपके खाने में क्या है।",
      heroLede: "पैक की फ़ोटो लें, बारकोड स्कैन करें या लेबल पेस्ट करें। LabelCheck हर सामग्री को WHO और FSSAI मानकों से जाँचकर आसान शब्दों में बताता है कि आपके लिए इसका क्या मतलब है।",
      photoHint: "सामग्री सूची और पोषण तालिका", barcodeHint: "जाने-माने ब्रांड के लिए सबसे तेज़",
      typeHint: "पैक या शॉपिंग साइट से पेस्ट करें", sampleTag: "नमूना रिपोर्ट",
      sampleVerdict: "कभी-कभार ही खाएँ", sampleServing: "70 ग्राम की एक सर्विंग में दैनिक सीमा का हिस्सा",
      sampleSalt: "नमक", sampleSatFat: "संतृप्त वसा", sampleSugar: "चीनी",
      standardsLead: "इन संस्थाओं के सार्वजनिक मानकों से जाँचा गया", featuresTitle: "रिपोर्ट आपको क्या बताती है",
      f1t: "साफ़ स्कोर और चेतावनियाँ", f1d: "0–100 का स्कोर और A–E ग्रेड, साथ में FSSAI द्वारा प्रस्तावित अधिक चीनी, नमक और वसा की चेतावनियाँ।",
      f2t: "हर एडिटिव की जानकारी", f2d: "हर INS नंबर की सुरक्षित दैनिक सीमा, कैंसर वर्गीकरण, FSSAI स्थिति और दूसरे देशों में प्रतिबंध की जाँच।",
      f3t: "नियमित सेवन का असर", f3d: "अक्सर खाने से जुड़े स्वास्थ्य प्रभाव, प्रमाण कितने मज़बूत हैं, और लंबे समय की तस्वीर दिखाता छोटा वीडियो।",
      f4t: "आपके लिए सलाह", f4d: "डायबिटीज़, ब्लड प्रेशर, किडनी रोग, गर्भावस्था, बच्चों, एलर्जी और शाकाहारी, वीगन या जैन आहार के लिए।",
      f5t: "बेहतर विकल्प", f5d: "दूसरे ख़रीदारों को मिले बेहतर स्कोर वाले उत्पाद, और भारतीय रसोई के आसान बदलाव।",
      f6t: "आपका डेटा आपका", f6d: "LabelCheck आपकी फ़ोटो नहीं सहेजता, और आपकी स्वास्थ्य प्रोफ़ाइल सिर्फ़ आपके फ़ोन पर रहती है।",
      howTitle: "यह कैसे काम करता है", s1t: "लेबल स्कैन या टाइप करें", s1d: "फ़ोटो, बारकोड या पेस्ट किया टेक्स्ट।",
      s2t: "पढ़ी गई जानकारी जाँचें", s2d: "रिपोर्ट बनने से पहले कोई भी संख्या ठीक करें।",
      s3t: "अपनी रिपोर्ट पढ़ें", s3d: "स्कोर, चेतावनियाँ, जोखिम और बेहतर विकल्प।",
      processing: "प्रसंस्करण", gradeAria: (g, s) => `ग्रेड ${g}, 100 में से ${s}`,
      photoLabel: "लेबल की फ़ोटो लें", scanBarcode: "बारकोड स्कैन करें", recent: "हाल की जाँचें", back: "वापस",
      captureTitle: "लेबल की फ़ोटो जोड़ें",
      captureLede: "सबसे अच्छे नतीजे के लिए सामग्री सूची और पोषण तालिका दोनों की फ़ोटो जोड़ें। फ़ोन सीधा रखें और लिखावट से फ़्रेम भरें।",
      addPhoto: "फ़ोटो जोड़ें", photoLimit: "अधिकतम 4 फ़ोटो। रिपोर्ट से पहले आप पढ़ी गई जानकारी जाँचकर ठीक कर सकते हैं।",
      checkFood: "यह भोजन जाँचें", scanTitle: "बारकोड पर कैमरा रखें", scanHint: "लगभग 15 सेमी दूर से स्थिर रखें।",
      typeBarcode: "या बारकोड के नीचे लिखा नंबर टाइप करें", look: "खोजें", workingHint: "आमतौर पर 5 से 15 सेकंड लगते हैं।",
      newCheck: "नई जाँच", share: "शेयर करें", profileTitle: "रिपोर्ट को अपने अनुसार बनाएँ",
      profilePrivacy: "यह सिर्फ़ इसी फ़ोन पर सहेजा जाता है। सलाह आपके अनुसार बनाने के लिए हर जाँच के साथ भेजा जाता है, सर्वर पर कभी सहेजा नहीं जाता।",
      ageGroup: "कौन खाएगा?", conditions: "स्वास्थ्य स्थितियाँ", allergies: "एलर्जी", cancel: "रद्द करें",
      saveProfile: "प्रोफ़ाइल सहेजें", footer: "सामान्य जानकारी, चिकित्सीय सलाह नहीं। उत्पाद डेटा आंशिक रूप से Open Food Facts (ODbL) से।",
      steps: ["लेबल पढ़ा जा रहा है…", "सामग्री को WHO और FSSAI सीमाओं से जाँचा जा रहा है…", "बेहतर विकल्प खोजे जा रहे हैं…", "आपकी रिपोर्ट तैयार हो रही है…"],
      barcodeSteps: ["बारकोड खोजा जा रहा है…", "सामग्री को WHO और FSSAI सीमाओं से जाँचा जा रहा है…", "आपकी रिपोर्ट तैयार हो रही है…"],
      whatItMeans: "इसका मतलब", perServing: "एक सर्विंग में दैनिक सीमा का हिस्सा",
      perServingNote: (who, size) => `${who} के लिए दैनिक सीमा का हिस्सा, ${size} की एक सर्विंग में।`,
      noServing: "पैक पर सर्विंग का आकार नहीं है, इसलिए 100 ग्राम की तुलना दैनिक सीमा से की गई है।",
      nutrition: (u) => `पोषण प्रति 100 ${u}`, scoreHow: "स्कोर कैसे निकाला गया", ingredients: "इसमें क्या है",
      additives: "एडिटिव (योजक)", noAdditives: "सामग्री सूची में कोई एडिटिव नहीं मिला।", flagsT: "ध्यान देने योग्य",
      allergensT: "इसमें है", traces: "इसमें हो सकता है", healthT: "लंबे समय के जुड़े प्रभाव",
      healthIntro: "ये नियमित और अधिक सेवन से जुड़े हैं। एक पैकेट से बीमारी नहीं होती।",
      noRisks: "इस उत्पाद में लंबे समय की कोई बड़ी चिंता नहीं मिली।",
      longTerm: "अगर आप इसे नियमित खाएँ", howOften: "कितनी बार", forHowLong: "कितने समय तक", makeVideo: "वीडियो बनाएँ",
      videoMaking: "आपका वीडियो बन रहा है… लगभग 5 सेकंड।", videoFailed: "वीडियो नहीं बन सका। एक मिनट बाद फिर कोशिश करें।",
      videoNote: "यह सामान्य वैज्ञानिक प्रमाणों का चित्रण है, किसी व्यक्ति के लिए भविष्यवाणी नहीं।",
      alternatives: "बेहतर विकल्प", fromScans: "LabelCheck पर बेहतर स्कोर वाले", fromOFF: "भारत में Nutri-Score A या B (Open Food Facts)",
      homeSwaps: "आसान बदलाव", dataQuality: "इस जाँच के बारे में", sources: "स्रोत", forYou: "आपके लिए",
      suitable: "आपकी प्रोफ़ाइल के लिए ठीक लगता है", caution: "सावधान रहें", notSuitable: "आपके लिए उपयुक्त नहीं",
      addProfile: "निजी सलाह के लिए अपनी स्वास्थ्य स्थितियाँ या एलर्जी जोड़ें।", setProfile: "प्रोफ़ाइल बनाएँ",
      linkCopied: "लिंक कॉपी हो गया", nutriScore: "Nutri-Score", nova: "प्रसंस्करण स्तर (NOVA)",
      freq: { 1: "हफ़्ते में एक बार", 3: "हफ़्ते में 3 बार", 7: "रोज़", 14: "दिन में दो बार" },
      yearsL: (y) => `${y} साल`,
      level: { low: "कम", medium: "मध्यम", high: "अधिक", unknown: "नहीं दिया" },
      age: { child: "बच्चा (4–12)", teen: "किशोर", adult: "वयस्क", senior: "वरिष्ठ (60+)" },
      cond: { diabetes: "डायबिटीज़", hypertension: "हाई ब्लड प्रेशर", heart_disease: "हृदय रोग", kidney_disease: "किडनी रोग",
        pregnancy: "गर्भावस्था", pku: "PKU", gout: "गाउट", asthma: "अस्थमा", thyroid_condition: "थायरॉइड", weight_loss: "वज़न घटाना" },
      allergen: { gluten: "ग्लूटेन (गेहूँ)", milk: "दूध", egg: "अंडा", peanut: "मूँगफली", tree_nuts: "मेवे", soy: "सोया",
        fish: "मछली", crustacean: "झींगा/शेलफ़िश", sesame: "तिल", mustard: "सरसों", sulphites: "सल्फ़ाइट" },
      who: { child: "बच्चे", teen: "किशोर", adult: "वयस्क", senior: "बुज़ुर्ग" },
      byAI: "इस रिपोर्ट के तथ्यों से AI द्वारा लिखा गया।", byTemplate: "मानक सारांश।",
      nutrientNames: { energy_kcal: "ऊर्जा", fat_g: "वसा", saturated_fat_g: "संतृप्त वसा", trans_fat_g: "ट्रांस फ़ैट",
        carbohydrates_g: "कार्बोहाइड्रेट", sugars_g: "चीनी", added_sugars_g: "अतिरिक्त चीनी", fiber_g: "फ़ाइबर", protein_g: "प्रोटीन",
        salt_g: "नमक", sodium_mg: "सोडियम" },
      nutrition_pts: "पोषण", processing_pts: "प्रसंस्करण", additive_pts: "एडिटिव",
      adi: "सुरक्षित दैनिक सीमा (ADI)", adiNone: "संख्यात्मक सीमा की ज़रूरत नहीं", iarc: "IARC समूह", fssai: "FSSAI",
      confidenceLow: "लेबल का कुछ हिस्सा पढ़ना मुश्किल था। मुख्य आँकड़े पैक से मिलाएँ।",
      offline: "आप ऑफ़लाइन हैं। जाँच के लिए इंटरनेट से जुड़ें।",
      labelOff: "इस सर्वर पर अभी फ़ोटो पढ़ना उपलब्ध नहीं है। आप लेबल टाइप कर सकते हैं या बारकोड स्कैन कर सकते हैं।",
      shareText: "फ़ूड लेबल जाँच",
      tooMany: "आप अधिकतम 4 फ़ोटो जोड़ सकते हैं।", needPhoto: "लेबल की कम से कम एक फ़ोटो जोड़ें।",
      cameraBlocked: "कैमरा की अनुमति बंद है। ब्राउज़र सेटिंग में अनुमति दें, या नीचे बारकोड टाइप करें।",
      noCamera: "इस डिवाइस पर कैमरा उपलब्ध नहीं है। नीचे बारकोड टाइप करें।",
      scanning: "स्कैन हो रहा है…", found: (c) => `मिला: ${c}`, perUnit: (u) => `प्रति 100 ${u}`,
      evidence: { strong: "मज़बूत प्रमाण", moderate: "मध्यम प्रमाण", limited: "सीमित प्रमाण" },
      verdicts: { A: "अच्छा विकल्प", B: "नियमित रूप से ठीक", C: "कभी-कभी ठीक", D: "कभी-कभार ही खाएँ", E: "नियमित सेवन से बचें" },
      readMore: "स्रोत पढ़ें", ingredientList: "पढ़ी गई सामग्री सूची",
      notOnLabel: (x) => `लेबल पर नहीं दिया: ${x}।`, unknownCodes: (x) => `ये कोड अभी हमारी सूची में नहीं हैं: ${x}।`,
      typeLabel: "लेबल टाइप करें", textTitle: "लेबल टाइप या पेस्ट करें",
      textLede: "पैक या शॉपिंग साइट से सामग्री सूची और पोषण तालिका कॉपी करें। “Ingredients” से शुरू होने वाली पंक्ति ज़रूर शामिल करें।",
      productName: "उत्पाद का नाम", brand: "ब्रांड", labelText: "लेबल का टेक्स्ट", readLabel: "लेबल पढ़ें",
      textTooShort: "लेबल का थोड़ा और हिस्सा पेस्ट करें: कम से कम सामग्री सूची या पोषण तालिका।",
      reviewTitle: "जो पढ़ा गया, उसे जाँचें",
      reviewLede: "इन्हें पैक से मिलाएँ और जो ग़लत हो उसे ठीक करें। जो लेबल पर नहीं है, उसका बॉक्स ख़ाली छोड़ दें।",
      readBy: { claude: "AI (Claude) द्वारा पढ़ा गया।", gemini: "AI (Gemini) द्वारा पढ़ा गया।", ocr: "साधारण टेक्स्ट पहचान से पढ़ा गया। कृपया हर संख्या जाँचें।",
        text: "आपके दर्ज किए टेक्स्ट से पढ़ा गया।", open_food_facts: "Open Food Facts (सार्वजनिक उत्पाद डेटाबेस) से।", manual: "हाथ से दर्ज किया गया।" },
      category: "भोजन का प्रकार", isDrink: "यह पेय है (मान प्रति 100 ml)", servingSize: "सर्विंग का आकार",
      vegMark: "शाकाहारी / मांसाहारी चिह्न", vegMarkOpts: { "": "नहीं दिखा", veg: "हरा (शाकाहारी)", non_veg: "भूरा (मांसाहारी)" },
      nutritionPer: (u) => `पोषण प्रति 100 ${u}`, ingredientsField: "सामग्री",
      needSomething: "पहले पोषण मान या सामग्री सूची जोड़ें।",
      missingNutrition: "कुछ मुख्य पोषण मान ख़ाली हैं, इसलिए स्कोर कम भरोसेमंद होगा।",
      editDetails: "विवरण बदलें", diet: "आहार",
      diets: { any: "कोई पाबंदी नहीं", vegetarian: "शाकाहारी (अंडा नहीं)", eggetarian: "शाकाहारी + अंडा", vegan: "वीगन", jain: "जैन" },
      readSteps: ["लेबल पढ़ा जा रहा है…", "सामग्री सूची खोजी जा रही है…", "पोषण तालिका पढ़ी जा रही है…"],
      analyzeSteps: ["सामग्री को WHO और FSSAI सीमाओं से जाँचा जा रहा है…", "बेहतर विकल्प खोजे जा रहे हैं…", "आपकी रिपोर्ट तैयार हो रही है…"],
      videoUnsupported: "यह ब्राउज़र यहाँ वीडियो नहीं चला पा रहा। डाउनलोड करके देखें।", download: "वीडियो डाउनलोड करें",
      reviewed: "आपने ये मान जाँचे हैं।",
      categories: { instant_noodles: "इंस्टेंट नूडल्स", chips_namkeen: "चिप्स और नमकीन", biscuits_cookies: "बिस्कुट और कुकीज़",
        chocolate_confectionery: "चॉकलेट और कैंडी", sugary_drink: "सॉफ़्ट ड्रिंक", fruit_juice: "पैक्ड जूस", energy_drink: "एनर्जी ड्रिंक",
        breakfast_cereal: "ब्रेकफ़ास्ट सीरियल", health_drink_powder: "माल्ट / हेल्थ ड्रिंक पाउडर", dairy_drink: "फ़्लेवर्ड दूध",
        yogurt_dessert: "फ़्लेवर्ड दही / डेज़र्ट", ice_cream: "आइसक्रीम / फ़्रोज़न डेज़र्ट", bread_bakery: "ब्रेड और बेकरी",
        sauce_spread: "सॉस और स्प्रेड", ready_meal: "रेडी-टू-ईट भोजन", processed_meat: "प्रोसेस्ड मीट", sweets_mithai: "पैक्ड मिठाई",
        cooking_oil_fat: "खाना पकाने का तेल / वसा", other: "पैक्ड भोजन" },
    },
  };

  // ---------------------------------------------------------------- state
  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } },
  };
  const state = {
    lang: store.get("lc.lang", (navigator.language || "").startsWith("hi") ? "hi" : "en"),
    profile: { age_group: "adult", diet: "any", conditions: [], allergies: [], ...store.get("lc.profile", {}) },
    photos: [],
    draft: null,
    report: null,
    meta: null,
    sim: { per_week: 7, years: 10 },
    scanStop: null,
  };
  const t = (key) => (T[state.lang][key] !== undefined ? T[state.lang][key] : T.en[key]);

  // ---------------------------------------------------------------- dom helpers
  const $ = (sel) => document.querySelector(sel);
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  const fmt = (n, digits = 1) => (n === null || n === undefined ? "—" : Number(n).toLocaleString(state.lang === "hi" ? "hi-IN" : "en-IN", { maximumFractionDigits: digits }));

  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const v = t(node.dataset.i18n);
      if (typeof v === "string") node.textContent = v;
    });
    $("#lang-toggle").textContent = state.lang === "hi" ? "EN" : "हिं";
    $("#lang-toggle").setAttribute("aria-label", state.lang === "hi" ? "Switch to English" : "हिंदी में देखें");
  }

  // ---------------------------------------------------------------- API
  async function api(path, options = {}) {
    if (!navigator.onLine) throw new Error(t("offline"));
    let res;
    try {
      res = await fetch(path, options);
    } catch {
      throw new Error(t("offline"));
    }
    let body = null;
    try { body = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) throw new Error((body && body.error) || `Request failed (${res.status}).`);
    return body;
  }
  const profilePayload = () => ({ ...state.profile, language: state.lang });
  const profileQuery = () => "profile=" + encodeURIComponent(JSON.stringify(profilePayload()));

  // ---------------------------------------------------------------- views
  const VIEWS = ["home", "capture", "text", "review", "scan", "loading", "report"];
  function show(name) {
    VIEWS.forEach((v) => { $(`#view-${v}`).hidden = v !== name; });
    if (name !== "scan") stopScanner();
    window.scrollTo(0, 0);
    $("#main").focus({ preventScroll: true });
  }

  let stepTimer = null;
  function working(steps) {
    show("loading");
    let i = 0;
    const node = $("#working-step");
    node.textContent = steps[0];
    clearInterval(stepTimer);
    stepTimer = setInterval(() => { i = Math.min(i + 1, steps.length - 1); node.textContent = steps[i]; }, 2600);
  }
  const stopWorking = () => clearInterval(stepTimer);

  function goHome(push = true) {
    if (push && location.pathname !== "/") history.pushState({}, "", "/");
    renderRecent();
    show("home");
  }

  // ---------------------------------------------------------------- home
  function renderRecent() {
    const items = store.get("lc.recent", []);
    const list = $("#recent-list");
    list.replaceChildren();
    $("#recent-wrap").hidden = items.length === 0;
    for (const r of items.slice(0, 8)) {
      list.append(el("li", {}, el("a", { href: `/r/${r.id}`, onclick: (e) => { e.preventDefault(); openReport(r.id); } },
        el("span", { class: "hex", "data-grade": r.grade, "aria-label": `Grade ${r.grade}`, text: r.grade }),
        el("span", { class: "recent-name", text: r.name }),
        el("span", { class: "recent-date", text: `${r.score}/100` }))));
    }
  }
  function remember(report) {
    const items = store.get("lc.recent", []).filter((r) => r.id !== report.report_id);
    items.unshift({ id: report.report_id, name: report.product.name, grade: report.analysis.grade, score: report.analysis.score });
    store.set("lc.recent", items.slice(0, 20));
  }

  async function checkServer() {
    try {
      const h = await api("/api/v1/health");
      const note = $("#server-note");
      note.hidden = !!h.label_reading_enabled;
      note.textContent = t("labelOff");
    } catch { /* offline: ignore */ }
  }

  // ---------------------------------------------------------------- photos
  async function compress(file) {
    // Downscale on the phone so uploads are quick on mobile data.
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close && bitmap.close();
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
      return blob || file;
    } catch {
      return file; // the server re-encodes anyway
    }
  }

  function renderShots() {
    const wrap = $("#shots");
    wrap.replaceChildren();
    state.photos.forEach((p, i) => {
      wrap.append(el("div", { class: "shot" },
        el("img", { src: p.url, alt: `Photo ${i + 1}` }),
        el("button", { type: "button", "aria-label": `Remove photo ${i + 1}`, text: "×", onclick: () => {
          URL.revokeObjectURL(p.url);
          state.photos.splice(i, 1);
          renderShots();
        } })));
    });
    $("#analyze-btn").disabled = state.photos.length === 0;
    $("#add-photo-label").hidden = state.photos.length >= 4;
  }

  async function addPhotos(files) {
    const err = $("#capture-error");
    err.hidden = true;
    for (const f of files) {
      if (state.photos.length >= 4) { err.textContent = t("tooMany"); err.hidden = false; break; }
      const blob = await compress(f);
      state.photos.push({ blob, url: URL.createObjectURL(blob) });
    }
    renderShots();
  }

  async function readPhotos() {
    const err = $("#capture-error");
    if (!state.photos.length) { err.textContent = t("needPhoto"); err.hidden = false; return; }
    const form = new FormData();
    state.photos.forEach((p, i) => form.append("files", p.blob, `label-${i + 1}.jpg`));
    working(t("readSteps"));
    try {
      const draft = await api("/api/v1/label/read", { method: "POST", body: form });
      state.photos.forEach((p) => URL.revokeObjectURL(p.url));
      state.photos = [];
      renderShots();
      openReview(draft.product, draft.notes || [], "capture");
    } catch (e) {
      show("capture");
      err.textContent = e.message;
      err.hidden = false;
    } finally {
      stopWorking();
    }
  }

  // ---------------------------------------------------------------- typed label
  async function readText(e) {
    e.preventDefault();
    const err = $("#text-error");
    err.hidden = true;
    const text = $("#text-body").value.trim();
    if (text.length < 20) { err.textContent = t("textTooShort"); err.hidden = false; return; }
    const name = $("#text-name").value.trim() || null;
    working(t("readSteps"));
    try {
      const draft = await api("/api/v1/label/text", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, name }),
      });
      openReview(draft.product, draft.notes || [], "text");
    } catch (ex) {
      show("text");
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      stopWorking();
    }
  }

  // ---------------------------------------------------------------- review & correct
  const NUTRIENT_FIELDS = [
    ["energy_kcal", "kcal"], ["protein_g", "g"], ["carbohydrates_g", "g"], ["sugars_g", "g"], ["added_sugars_g", "g"],
    ["fat_g", "g"], ["saturated_fat_g", "g"], ["trans_fat_g", "g"], ["fiber_g", "g"], ["sodium_mg", "mg"], ["salt_g", "g"],
  ];
  const KEY_NUTRIENTS = ["energy_kcal", "sugars_g", "saturated_fat_g", "sodium_mg"];

  function numField(name, label, unit, value) {
    return el("label", { class: "field field-num" }, el("span", { text: label }),
      el("span", { class: "with-unit" },
        el("input", { name, type: "text", inputmode: "decimal", autocomplete: "off", value: value ?? "", "aria-label": `${label} (${unit})` }),
        el("i", { text: unit })));
  }

  async function openReview(product, notes, from) {
    const meta = await loadMeta();
    state.draft = { product: JSON.parse(JSON.stringify(product)), from };
    const p = state.draft.product;
    const n = p.nutrition || {};
    const unit = p.is_liquid ? "ml" : "g";

    const note = $("#review-note");
    const readBy = t("readBy")[p.read_by || p.source] || "";
    note.replaceChildren(...[
      readBy ? el("p", { class: p.read_by === "ocr" || p.extraction_confidence === "low" ? "warn" : "", text: readBy }) : null,
      notes.length ? el("ul", { class: "points quality" }, notes.map((x) => el("li", { text: x }))) : null,
    ].filter(Boolean));
    note.hidden = !readBy && !notes.length;

    const catNames = t("categories") || {};
    const cats = Object.entries(meta.categories || { other: "Packaged food" });
    const form = $("#review-form");
    form.replaceChildren(...[
      el("label", { class: "field" }, el("span", { text: t("productName") }), el("input", { name: "name", maxlength: 200, value: p.name === "Unnamed product" ? "" : p.name })),
      el("label", { class: "field" }, el("span", { text: t("brand") }), el("input", { name: "brand", maxlength: 120, value: p.brand || "" })),
      el("label", { class: "field" }, el("span", { text: t("category") }),
        el("select", { name: "category" }, cats.map(([k, v]) => el("option", { value: k, selected: k === p.category || null, text: catNames[k] || v })))),
      el("label", { class: "check" }, el("input", { type: "checkbox", name: "is_liquid", checked: p.is_liquid || null }), el("span", { text: t("isDrink") })),
      el("div", { class: "field-row" },
        numField("serving_size_g", t("servingSize"), unit, p.serving_size_g),
        el("label", { class: "field" }, el("span", { text: t("vegMark") }),
          el("select", { name: "veg_mark" }, Object.entries(t("vegMarkOpts")).map(([k, v]) =>
            el("option", { value: k, selected: (p.veg_mark || "") === k || null, text: v }))))),
      el("fieldset", { class: "nut" }, el("legend", { id: "nut-legend", text: t("nutritionPer")(unit) }),
        el("div", { class: "nut-grid" }, NUTRIENT_FIELDS.map(([k, u]) => numField(k, t("nutrientNames")[k], u, n[k])))),
      el("label", { class: "field" }, el("span", { text: t("ingredientsField") }),
        el("textarea", { name: "ingredients_text", rows: 6, maxlength: 6000, spellcheck: "false" }, p.ingredients_text || "")),
      KEY_NUTRIENTS.some((k) => (n[k] ?? null) === null && !(k === "sodium_mg" && (n.salt_g ?? null) !== null))
        ? el("p", { class: "hint warn-text", text: t("missingNutrition") }) : null,
      el("p", { class: "error", id: "review-error", role: "alert", hidden: true }),
      el("button", { class: "btn btn-primary btn-big", type: "submit", text: t("checkFood") }),
    ].filter(Boolean));

    // Sodium and salt describe the same thing: editing one clears the other so they never disagree.
    const sodium = form.elements.sodium_mg;
    const salt = form.elements.salt_g;
    sodium.addEventListener("input", () => { salt.value = ""; });
    salt.addEventListener("input", () => { sodium.value = ""; });
    form.elements.is_liquid.addEventListener("change", (ev) => {
      const u = ev.target.checked ? "ml" : "g";
      $("#nut-legend").textContent = t("nutritionPer")(u);
      form.querySelector("input[name=serving_size_g]").nextElementSibling.textContent = u;
    });
    show("review");
  }

  function parseNum(raw) {
    const s = String(raw || "").trim().replace(",", ".");
    if (!s) return null;
    const v = Number(s);
    return Number.isFinite(v) && v >= 0 ? v : NaN;
  }

  async function submitReview(e) {
    e.preventDefault();
    const form = $("#review-form");
    const err = $("#review-error");
    err.hidden = true;
    const p = state.draft.product;
    const nutrition = {};
    let bad = null;
    for (const [k] of NUTRIENT_FIELDS) {
      const v = parseNum(form.elements[k].value);
      if (Number.isNaN(v)) bad = bad || t("nutrientNames")[k];
      nutrition[k] = Number.isNaN(v) ? null : v;
    }
    const serving = parseNum(form.elements.serving_size_g.value);
    if (Number.isNaN(serving)) bad = bad || t("servingSize");
    if (bad) { err.textContent = `${bad}: ${state.lang === "hi" ? "सही संख्या लिखें" : "enter a number"}.`; err.hidden = false; form.elements[0].focus(); return; }
    const ingredients = form.elements.ingredients_text.value.trim();
    const hasNutrition = Object.values(nutrition).some((v) => v !== null);
    if (!hasNutrition && !ingredients) { err.textContent = t("needSomething"); err.hidden = false; return; }

    const product = {
      ...p,
      name: form.elements.name.value.trim() || "Unnamed product",
      brand: form.elements.brand.value.trim() || null,
      category: form.elements.category.value,
      is_liquid: form.elements.is_liquid.checked,
      serving_size_g: serving || null,
      veg_mark: form.elements.veg_mark.value || null,
      ingredients_text: ingredients || null,
      ingredients: [],
      nutrition,
      reviewed: true,
    };
    working(t("analyzeSteps"));
    try {
      const report = await api("/api/v1/analyze/product", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product, profile: profilePayload(), explain: true }),
      });
      showReport(report, true);
    } catch (ex) {
      show("review");
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      stopWorking();
    }
  }

  // ---------------------------------------------------------------- barcode
  const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];

  async function startScanner() {
    show("scan");
    const status = $("#scan-status");
    const errBox = $("#scan-error");
    errBox.hidden = true;
    status.textContent = t("scanHint");
    const video = $("#scan-video");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("#viewfinder").hidden = true;
      errBox.textContent = t("noCamera");
      errBox.hidden = false;
      return;
    }
    $("#viewfinder").hidden = false;

    if ("BarcodeDetector" in window) {
      try {
        const supported = await window.BarcodeDetector.getSupportedFormats();
        const formats = FORMATS.filter((f) => supported.includes(f));
        if (formats.length) {
          const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
          video.srcObject = stream;
          await video.play();
          const detector = new window.BarcodeDetector({ formats });
          let active = true;
          state.scanStop = () => { active = false; stream.getTracks().forEach((tr) => tr.stop()); video.srcObject = null; };
          const loop = async () => {
            if (!active) return;
            try {
              const codes = await detector.detect(video);
              if (codes.length) { onBarcode(codes[0].rawValue); return; }
            } catch { /* frame not ready */ }
            setTimeout(loop, 220);
          };
          loop();
          return;
        }
      } catch (e) {
        return cameraError(e);
      }
    }
    // Fallback for browsers without BarcodeDetector (e.g. iPhone Safari).
    try {
      const { BrowserMultiFormatReader } = await import("https://cdn.jsdelivr.net/npm/@zxing/browser@0.1/+esm");
      const reader = new BrowserMultiFormatReader();
      const controls = await reader.decodeFromConstraints({ video: { facingMode: "environment" } }, video, (result) => {
        if (result) onBarcode(result.getText());
      });
      state.scanStop = () => controls.stop();
    } catch (e) {
      cameraError(e);
    }
  }
  function cameraError(e) {
    const errBox = $("#scan-error");
    errBox.textContent = e && e.name === "NotAllowedError" ? t("cameraBlocked") : t("noCamera");
    errBox.hidden = false;
    $("#viewfinder").hidden = true;
  }
  function stopScanner() {
    if (state.scanStop) { try { state.scanStop(); } catch { /* already stopped */ } state.scanStop = null; }
  }
  let handlingBarcode = false;
  async function onBarcode(code) {
    const digits = String(code).replace(/\D/g, "");
    if (!/^\d{6,14}$/.test(digits) || handlingBarcode) return;
    handlingBarcode = true;
    stopScanner();
    if (navigator.vibrate) navigator.vibrate(60);
    working(t("barcodeSteps"));
    try {
      const report = await api(`/api/v1/products/barcode/${digits}?${profileQuery()}`);
      showReport(report, true);
    } catch (e) {
      show("scan");
      $("#viewfinder").hidden = true;
      $("#barcode-input").value = digits;
      const errBox = $("#scan-error");
      errBox.textContent = e.message;
      errBox.hidden = false;
    } finally {
      stopWorking();
      handlingBarcode = false;
    }
  }

  // ---------------------------------------------------------------- report
  async function openReport(id, push = true) {
    working([t("steps")[3]]);
    try {
      const report = await api(`/api/v1/reports/${encodeURIComponent(id)}?${profileQuery()}`);
      showReport(report, push);
    } catch (e) {
      goHome();
      const note = $("#server-note");
      note.textContent = e.message;
      note.hidden = false;
    } finally {
      stopWorking();
    }
  }

  function showReport(report, push) {
    state.report = report;
    remember(report);
    if (push) history.pushState({ report: report.report_id }, "", `/r/${report.report_id}`);
    renderReport(report);
    show("report");
  }

  // Grade seal: a hexagon (after FSSAI's warning symbol) whose outline fills with the score.
  const SVG_NS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function seal(grade, score, animate) {
    const pts = "60,6 112,36 112,96 60,126 8,96 8,36";
    const svg = svgEl("svg", { class: `seal${animate ? " drawing" : ""}`, viewBox: "0 0 120 132", "data-grade": grade,
      role: "img", "aria-label": t("gradeAria")(grade, score) });
    svg.append(
      svgEl("polygon", { class: "seal-fill", points: pts }),
      svgEl("polygon", { class: "seal-track", points: pts, pathLength: "100" }),
      svgEl("polygon", { class: "seal-ring", points: pts, pathLength: "100", style: `stroke-dasharray:${Math.max(1, score)} 100` }),
      svgEl("text", { class: "seal-letter", x: "60", y: "72" }, grade),
      svgEl("text", { class: "seal-score", x: "60", y: "98" }, `${score}/100`));
    return svg;
  }

  function block(title, ...children) {
    return el("section", { class: "block" }, el("h2", { text: title }), ...children);
  }

  function renderReport(r) {
    const a = r.analysis;
    const p = r.product;
    const unit = p.is_liquid ? "ml" : "g";
    const root = $("#report");
    root.replaceChildren();

    // Summary column: grade seal, verdict, warnings, personal advice.
    const headCol = el("header", { class: "report-head" });
    const body = el("div", { class: "report-body" });
    const by = [p.brand, p.net_quantity].filter(Boolean).join(", ");
    const summary = el("div", { class: "summary-card" },
      el("div", { class: "verdict", "data-grade": a.grade },
        seal(a.grade, a.score, true),
        el("div", {},
          el("p", { class: "verdict-text", text: (t("verdicts") || {})[a.grade] || a.verdict }),
          el("ul", { class: "stats" },
            el("li", { text: `${t("nutriScore")} ${a.nutri_score.grade || "–"}` }),
            el("li", { text: `${t("processing")}: NOVA ${a.nova.group || "–"}` })))),
      el("h1", { text: p.name }),
      by ? el("p", { class: "byline", text: by }) : null,
      a.front_of_pack_warnings.length ? el("ul", { class: "warnings", "aria-label": "Front-of-pack warnings" },
        a.front_of_pack_warnings.map((w) => el("li", { class: "warning", text: w }))) : null);
    headCol.append(summary);

    // Personal
    const per = r.personal;
    if (per.profile_applied) {
      const head = { not_suitable: t("notSuitable"), caution: t("caution"), suitable: t("suitable") }[per.suitability];
      headCol.append(el("div", { class: "personal", "data-s": per.suitability },
        el("h2", { text: head }),
        per.alerts.length ? el("ul", { class: "alerts" }, per.alerts.map((al) =>
          el("li", { "data-level": al.level }, el("b", { text: al.title }), al.detail))) : null));
    } else {
      headCol.append(el("div", { class: "personal" }, el("p", { text: t("addProfile") }),
        el("button", { class: "pill", type: "button", text: t("setProfile"), onclick: openProfile })));
    }

    // Explanation
    const ex = r.explanation;
    body.append(block(t("whatItMeans"),
      el("p", { class: "explain-head", text: ex.headline }),
      el("p", { text: ex.summary }),
      ex.key_points && ex.key_points.length ? el("ul", { class: "points" }, ex.key_points.map((k) => el("li", { text: k }))) : null,
      ex.who_should_be_careful ? el("p", { text: ex.who_should_be_careful }) : null,
      ex.tip ? el("p", { class: "tip" }, ex.tip) : null,
      el("p", { class: "source-note", text: ex.generated_by && ex.generated_by !== "template" ? t("byAI") : t("byTemplate") })));

    // Daily-limit meters
    const serving = per.per_serving;
    const limits = per.daily_limits;
    const meterKeys = ["salt_g", "sugars_g", "saturated_fat_g", "fat_g", "energy_kcal"];
    const meters = el("div", { class: "meters" });
    const n = p.nutrition;
    for (const key of meterKeys) {
      let pct = null;
      let amount = null;
      if (serving && serving.percent_of_daily_limit[key] !== undefined) {
        pct = serving.percent_of_daily_limit[key];
        amount = serving.values[key];
      } else if (!serving && n[key] !== null && n[key] !== undefined && limits[key]) {
        pct = Math.round((1000 * n[key]) / limits[key]) / 10;
        amount = n[key];
      }
      if (pct === null) continue;
      const lvl = pct >= 30 ? "high" : pct >= 15 ? "mid" : "low";
      const u = key === "energy_kcal" ? "kcal" : "g";
      meters.append(el("div", { class: "meter-row" },
        el("span", { text: `${t("nutrientNames")[key]}: ${fmt(amount, key === "energy_kcal" ? 0 : 1)} ${u}` }),
        el("span", { class: "val", text: `${fmt(pct, 0)}%` }),
        el("div", { class: "meter", role: "presentation" }, el("i", { "data-l": lvl, style: `width:${Math.min(100, pct)}%` }))));
    }
    if (meters.childElementCount) {
      const note = serving ? t("perServingNote")(t("who")[per.age_group] || per.age_group, `${fmt(serving.serving_size, 0)} ${unit}`) : t("noServing");
      body.append(block(t("perServing"), el("p", { class: "source-note", text: note }), meters));
    }

    // Nutrition table
    const rows = ["energy_kcal", "fat_g", "saturated_fat_g", "trans_fat_g", "carbohydrates_g", "sugars_g", "fiber_g", "protein_g", "salt_g", "sodium_mg"];
    const table = el("table", { class: "ntable" }, el("tbody", {}, rows.filter((k) => n[k] !== null && n[k] !== undefined).map((k) => {
      const lv = a.nutrient_levels[k];
      const u = k === "energy_kcal" ? "kcal" : k === "sodium_mg" ? "mg" : "g";
      return el("tr", { class: k === "energy_kcal" ? "thick" : null },
        el("td", { text: t("nutrientNames")[k] }), el("td", { text: `${fmt(n[k])} ${u}` }),
        el("td", {}, lv ? el("span", { class: "lvl", "data-l": lv.level, text: t("level")[lv.level] }) : ""));
    })));
    body.append(block(t("nutrition")(unit), table));

    // Score breakdown
    const b = a.breakdown;
    const rowsB = [
      [t("nutrition_pts"), `${fmt(b.nutrition.points)} / ${b.nutrition.max}`, b.nutrition.note],
      [t("processing_pts"), `${fmt(b.processing.points)} / ${b.processing.max}`, b.processing.note],
      [t("additive_pts"), `${fmt(b.additives.points)} / ${b.additives.max}`, b.additives.note],
    ];
    body.append(block(t("scoreHow"), el("div", { class: "breakdown" },
      rowsB.map(([k, v, note]) => el("div", { title: note }, el("span", { text: k }), el("span", { text: v }))),
      b.penalties.map((pen) => el("div", { class: pen.points < 0 ? "neg" : "" }, el("span", { text: pen.reason }), el("span", { text: pen.points ? String(pen.points) : "" })))),
      el("p", { class: "source-note", text: [b.nutrition.note, b.processing.note].join(" ") })));

    // Ingredients and additives
    const addList = el("ul", { class: "add-list" }, a.additives.map((ad) => el("li", {}, el("details", {},
      el("summary", {}, el("span", { class: "dot", "data-c": ad.concern, "aria-label": ad.concern }), el("span", { text: ad.name }), el("span", { class: "code", text: `INS ${ad.ins}` })),
      el("div", { class: "add-body" },
        el("p", { text: ad.note }),
        el("p", { class: "facts", text: `${ad.function}. ${t("adi")}: ${ad.adi ? `${ad.adi} mg/kg (${ad.adi_source})` : (ad.adi_note || t("adiNone"))}.` }),
        ad.iarc ? el("p", { class: "facts", text: `${t("iarc")}: ${ad.iarc}` }) : null,
        el("p", { class: "facts", text: `${t("fssai")}: ${ad.fssai}` }),
        (ad.regulatory || []).map((reg) => el("p", { class: "facts", text: reg })))))));
    const ing = [
      a.additives.length ? el("h3", { text: t("additives") }) : null,
      a.additives.length ? addList : el("p", { text: t("noAdditives") }),
    ];
    if (a.ingredient_flags.length) {
      ing.push(el("h3", { text: t("flagsT") }), el("ul", { class: "points" },
        a.ingredient_flags.filter((f) => f.severity !== "info").map((f) => el("li", {}, el("b", { text: f.label }), `. ${f.note}`))));
    }
    if (a.allergens.length || a.traces.length) {
      const names = t("allergen");
      ing.push(el("h3", { text: t("allergensT") }), el("ul", { class: "tags" },
        a.allergens.map((x) => el("li", { class: "strong", text: names[x] || x })),
        a.traces.map((x) => el("li", { text: `${t("traces")}: ${names[x] || x}` }))));
    }
    if (p.ingredients_text) ing.push(el("details", {}, el("summary", { text: t("ingredientList") }), el("p", { class: "source-note", text: p.ingredients_text })));
    body.append(block(t("ingredients"), ...ing));

    // Health effects
    body.append(block(t("healthT"),
      el("p", { class: "source-note", text: t("healthIntro") }),
      a.health_risks.length ? a.health_risks.map((risk) => el("div", { class: "risk" },
        el("h3", {}, risk.title, el("span", { class: "evidence", "data-e": risk.evidence, text: t("evidence")[risk.evidence] || risk.evidence })),
        el("p", { text: risk.reason }), el("p", { text: risk.effect }),
        el("p", { class: "source-note" }, el("a", { href: risk.url, target: "_blank", rel: "noopener", text: risk.source })))) : el("p", { text: t("noRisks") })));

    // Long-term simulation
    body.append(renderSimulation(r));

    // Alternatives
    const alt = r.alternatives;
    const altParts = [];
    if (alt.from_scans.length) {
      altParts.push(el("h3", { text: t("fromScans") }), el("ul", { class: "alt-list" }, alt.from_scans.map((x) => el("li", {},
        el("span", { class: "hex", "data-grade": x.grade, text: x.grade }),
        el("span", {}, el("b", { text: x.name }), x.brand ? el("span", { class: "why", text: ` ${x.brand}` }) : null, el("span", { class: "why", text: `  ${x.score}/100` }))))));
    }
    if (alt.from_open_food_facts.length) {
      altParts.push(el("h3", { text: t("fromOFF") }), el("ul", { class: "alt-list" }, alt.from_open_food_facts.map((x) => el("li", {},
        el("span", { class: "hex", "data-grade": x.nutri_score || "C", text: x.nutri_score || "?" }),
        el("span", {}, el("b", { text: x.name }), el("span", { class: "why", text: ` ${[x.brand, x.quantity].filter(Boolean).join(", ")}` }))))),
      el("p", { class: "source-note", text: alt.attribution }));
    }
    altParts.push(el("h3", { text: t("homeSwaps") }), el("ul", { class: "alt-list swap-list" }, alt.home_swaps.map((s) => el("li", {},
      el("span", {}, el("b", { text: s.name }), el("br"), el("span", { class: "why", text: s.why }))))));
    body.append(block(t("alternatives"), ...altParts));

    // Data quality, disclaimer and sources
    const dq = a.data_quality;
    const notes = [];
    if (dq.read_by && t("readBy")[dq.read_by]) notes.push(t("readBy")[dq.read_by]);
    if (dq.reviewed_by_user) notes.push(t("reviewed"));
    else if (dq.extraction_confidence === "low") notes.push(t("confidenceLow"));
    notes.push(...(dq.extraction_notes || []));
    if (dq.missing_nutrients && dq.missing_nutrients.length) notes.push(t("notOnLabel")(dq.missing_nutrients.join(", ")));
    if (dq.unrecognised_additive_codes && dq.unrecognised_additive_codes.length) notes.push(t("unknownCodes")(dq.unrecognised_additive_codes.join(", ")));
    if (notes.length) body.append(block(t("dataQuality"), el("ul", { class: "points quality" }, notes.map((x) => el("li", { text: x })))));
    body.append(el("p", { class: "disclaimer", text: r.disclaimer }));
    body.append(el("details", {}, el("summary", { text: t("sources") }),
      el("ul", { class: "sources" }, r.sources.map((s) => el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener", text: s.name }))))));
    root.append(headCol, body);
  }

  function renderSimulation(r) {
    const wrap = el("section", { class: "block" }, el("h2", { text: t("longTerm") }));
    const seg = (label, options, current, onPick) => el("div", {},
      el("span", { class: "seg-label", text: label }),
      el("div", { class: "seg", role: "group", "aria-label": label }, options.map(([value, text]) =>
        el("button", { type: "button", "aria-pressed": String(value === current), text, onclick: (e) => {
          e.currentTarget.parentElement.querySelectorAll("button").forEach((btn) => btn.setAttribute("aria-pressed", "false"));
          e.currentTarget.setAttribute("aria-pressed", "true");
          onPick(value);
        } }))));
    const freqText = t("freq");
    wrap.append(el("div", { class: "sim-controls" },
      seg(t("howOften"), [1, 3, 7, 14].map((v) => [v, freqText[v]]), state.sim.per_week, (v) => { state.sim.per_week = v; }),
      seg(t("forHowLong"), [1, 5, 10, 20].map((v) => [v, t("yearsL")(v)]), state.sim.years, (v) => { state.sim.years = v; })));
    const status = el("p", { class: "hint", "aria-live": "polite" });
    const video = el("video", { class: "sim-video", controls: true, playsinline: true, muted: true, preload: "auto", hidden: true });
    const download = el("a", { class: "pill", hidden: true, text: t("download") });
    const findings = el("ul", { class: "findings" });
    const button = el("button", { class: "btn btn-primary", type: "button", text: t("makeVideo"), onclick: async () => {
      const q = `per_week=${state.sim.per_week}&years=${state.sim.years}&age_group=${encodeURIComponent(state.profile.age_group || "adult")}`;
      status.textContent = t("videoMaking");
      button.disabled = true;
      video.hidden = true;
      download.hidden = true;
      try {
        const sim = await api(`/api/v1/reports/${r.report_id}/simulation?${q}`);
        findings.replaceChildren(...(sim.findings.length ? sim.findings.map((f) => el("li", {}, el("b", { text: `${f.label}: ` }), f.caption))
          : [el("li", { text: t("noRisks") })]));
        // H.264 MP4 first (phones, Safari, Chrome); VP9 WebM for browsers built without H.264.
        const fmt = video.canPlayType("video/mp4; codecs=\"avc1.42E01E\"") ? "mp4"
          : video.canPlayType("video/webm; codecs=\"vp9\"") ? "webm" : "mp4";
        const src = `/api/v1/reports/${r.report_id}/video.${fmt}?${q}`;
        download.href = src;
        download.setAttribute("download", `labelcheck-${r.report_id}.${fmt}`);
        video.onloadeddata = () => {
          status.textContent = t("videoNote"); video.hidden = false; download.hidden = false; button.disabled = false;
          video.play().catch(() => {});
        };
        video.onerror = () => {
          // The file exists but this browser can't play it: still offer the download.
          status.textContent = t("videoUnsupported"); download.hidden = false; button.disabled = false;
        };
        video.src = src;
        video.load();
      } catch (e) {
        status.textContent = e.message;
        button.disabled = false;
      }
    } });
    wrap.append(button, status, video, download, findings);
    return wrap;
  }

  // ---------------------------------------------------------------- profile
  async function loadMeta() {
    if (state.meta) return state.meta;
    try { state.meta = await api("/api/v1/meta"); } catch {
      state.meta = { conditions: Object.keys(T.en.cond), allergen_groups: Object.keys(T.en.allergen),
        diets: Object.keys(T.en.diets), categories: { other: "Packaged food" } };
    }
    return state.meta;
  }
  function chip(type, name, value, label, checked) {
    return el("label", {}, el("input", { type, name, value, checked: checked || null }), el("span", { text: label }));
  }
  async function openProfile() {
    const meta = await loadMeta();
    const pr = state.profile;
    $("#age-chips").replaceChildren(...["child", "teen", "adult", "senior"].map((v) => chip("radio", "age", v, t("age")[v], pr.age_group === v)));
    $("#diet-chips").replaceChildren(...(meta.diets || Object.keys(T.en.diets)).map((v) =>
      chip("radio", "diet", v, t("diets")[v] || v, (pr.diet || "any") === v)));
    $("#condition-chips").replaceChildren(...meta.conditions.map((v) => chip("checkbox", "cond", v, t("cond")[v] || v, pr.conditions.includes(v))));
    $("#allergy-chips").replaceChildren(...meta.allergen_groups.map((v) => chip("checkbox", "allergy", v, t("allergen")[v] || v, pr.allergies.includes(v))));
    $("#profile-dialog").showModal();
  }
  function saveProfile() {
    const form = $("#profile-form");
    const age = form.querySelector("input[name=age]:checked");
    const diet = form.querySelector("input[name=diet]:checked");
    state.profile = {
      age_group: age ? age.value : "adult",
      diet: diet ? diet.value : "any",
      conditions: [...form.querySelectorAll("input[name=cond]:checked")].map((i) => i.value),
      allergies: [...form.querySelectorAll("input[name=allergy]:checked")].map((i) => i.value),
    };
    store.set("lc.profile", state.profile);
    if (state.report && !$("#view-report").hidden) openReport(state.report.report_id, false);
  }

  // ---------------------------------------------------------------- share
  async function share() {
    if (!state.report) return;
    const url = `${location.origin}/r/${state.report.report_id}`;
    const title = `${state.report.product.name}: ${state.report.analysis.grade} (${state.report.analysis.score}/100)`;
    try {
      if (navigator.share) { await navigator.share({ title: t("shareText"), text: title, url }); return; }
      await navigator.clipboard.writeText(url);
      $("#share-btn").textContent = t("linkCopied");
      setTimeout(() => { $("#share-btn").textContent = t("share"); }, 2000);
    } catch { /* user cancelled */ }
  }

  // ---------------------------------------------------------------- wiring
  function route(push = false) {
    const m = location.pathname.match(/^\/r\/([A-Za-z0-9_-]{6,32})$/);
    if (m) openReport(m[1], push);
    else goHome(false);
  }

  document.addEventListener("click", (e) => {
    const nav = e.target.closest("[data-nav]");
    if (nav && nav.dataset.nav === "home") { e.preventDefault(); goHome(); }
  });
  $("#start-photo").addEventListener("click", () => { show("capture"); renderShots(); $("#photo-input").click(); });
  $("#photo-input").addEventListener("change", (e) => { addPhotos([...e.target.files]); e.target.value = ""; });
  $("#analyze-btn").addEventListener("click", readPhotos);
  $("#start-barcode").addEventListener("click", startScanner);
  $("#start-text").addEventListener("click", () => { show("text"); $("#text-body").focus(); });
  $("#text-form").addEventListener("submit", readText);
  $("#review-form").addEventListener("submit", submitReview);
  $("#edit-btn").addEventListener("click", () => {
    if (state.report) openReview(state.report.product, [], "report");
  });
  $("#barcode-form").addEventListener("submit", (e) => { e.preventDefault(); onBarcode($("#barcode-input").value); });
  $("#share-btn").addEventListener("click", share);
  $("#open-profile").addEventListener("click", openProfile);
  $("#profile-dialog").addEventListener("close", () => { if ($("#profile-dialog").returnValue === "save") saveProfile(); });
  $("#lang-toggle").addEventListener("click", () => {
    state.lang = state.lang === "hi" ? "en" : "hi";
    store.set("lc.lang", state.lang);
    applyI18n();
    if (state.report && !$("#view-report").hidden) openReport(state.report.report_id, false);
  });
  window.addEventListener("popstate", () => route(false));

  applyI18n();
  checkServer();
  route(false);

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
})();
