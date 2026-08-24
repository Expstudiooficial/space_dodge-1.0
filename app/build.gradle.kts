plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.chaquopy)
}

/**
 * Which ABIs to build for.
 *
 * Chaquopy's Python 3.13 runtime is 64-bit only, which matches every device
 * Play still accepts uploads for. x86_64 is included by default so the app also
 * runs on an emulator. Pass -Ppycmd.abi=arm64-v8a for a build aimed only at
 * real phones: Chaquopy bundles its Python assets for every ABI listed here and
 * does not take part in the APK splits, so dropping x86_64 saves about 3 MB
 * that no phone can use.
 */
val targetAbis: List<String> = (findProperty("pycmd.abi") as String?)
    ?.split(",")
    ?.map { it.trim() }
    ?.filter { it.isNotEmpty() }
    ?: listOf("arm64-v8a", "x86_64")

android {
    namespace = "com.expstudio.pycmd"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.expstudio.pycmd"
        minSdk = 24
        targetSdk = 35
        versionCode = 2
        versionName = "1.1"

        ndk {
            abiFilters += targetAbis
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    // One APK per ABI, plus a universal one, so a phone downloads only the
    // slice it can run. The split list is driven by the same targetAbis as the
    // native filters above: splitting on an ABI that was filtered out would
    // emit an APK with no native libraries in it at all.
    splits {
        abi {
            isEnable = targetAbis.size > 1
            reset()
            include(*targetAbis.toTypedArray())
            isUniversalApk = true
        }
    }

    lint {
        textReport = true
        xmlReport = true
        // A missing translation or a newer-dependency notice should not stop a
        // build; real correctness issues still surface in the report.
        abortOnError = false
        // ChromeOsAbiSupport: dropping x86_64 is a deliberate choice for the
        // phone-only build (-Ppycmd.abi=arm64-v8a); the default build keeps it.
        disable += setOf(
            "GradleDependency",
            "AndroidGradlePluginVersion",
            "OldTargetApi",
            "ChromeOsAbiSupport",
        )
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        // Chaquopy resolves the pip requirements below with a local CPython of
        // the same minor version. Override with
        // -Ppycmd.buildPython=/path/to/python3.13 if it is not on PATH.
        buildPython((findProperty("pycmd.buildPython") as String?) ?: "python3.13")

        pip {
            // Pure-Python batteries that are useful on a phone and always resolvable.
            install("requests==2.32.3")
            install("flask==3.0.3")
            install("rich==13.9.4")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir("src/main/python")
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.documentfile)
    implementation(libs.kotlinx.coroutines.android)

    debugImplementation(libs.androidx.ui.tooling)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
}

/**
 * Keeps the in-app copies of the documentation in step with the real ones.
 *
 * The app shows README, TUTORIAL and PLUGINS on the phone, and an asset copy
 * that drifts from the file people read on GitHub is worse than no copy: one
 * of the two is then lying. Copying at build time means there is one source.
 */
val syncDocs by tasks.registering(Copy::class) {
    from(rootProject.file("README.md"))
    from(rootProject.file("TUTORIAL.md"))
    from(rootProject.file("PLUGINS.md"))
    into(layout.projectDirectory.dir("src/main/assets/docs"))
}

tasks.named("preBuild") { dependsOn(syncDocs) }
