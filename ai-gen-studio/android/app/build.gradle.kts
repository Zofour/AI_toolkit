plugins {
    id("com.android.application")
}

android {
    namespace = "com.chatbox.aigenstudio"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.chatbox.aigenstudio"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

// 刻意不引入任何 AndroidX 依赖：只用框架 API，编译最快、最不容易出岔子
dependencies {
}
