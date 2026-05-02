let lightmode = localStorage.getItem('lightmode')
const theme = document.getElementById('theme-btn')

const enablelightmode = () => {
    document.body.classList.add('lightmode')
    localStorage.setItem('lightmode', 'active')
}

const disablelightmode = () => {
    document.body.classList.remove('lightmode')
    localStorage.setItem('lightmode', 'inactive')
}

if (lightmode === "active") enablelightmode()

theme.addEventListener('click', () => {
    console.log('clicked')
    lightmode = localStorage.getItem('lightmode')
    lightmode !== "active" ? enablelightmode() : disablelightmode()
})