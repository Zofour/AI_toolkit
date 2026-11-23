plugins {
    id("com.android.application")
}

android {
    namespace = "com.chatbox.paperscan"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.chatbox.paperscan"
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

// 刻意不引入任何 AndroidX / 第三方依赖：全用框架 API，构建最快最稳
dependencies {
}
