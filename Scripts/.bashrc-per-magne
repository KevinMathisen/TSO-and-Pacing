# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for examples

# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

resize -s 50 100 >/dev/null

# don't put duplicate lines or lines starting with space in the history.
# See bash(1) for more options
HISTCONTROL=ignoreboth

# append to the history file, don't overwrite it
shopt -s histappend

# for setting history length see HISTSIZE and HISTFILESIZE in bash(1)
HISTSIZE=1000
HISTFILESIZE=2000

# check the window size after each command and, if necessary,
# update the values of LINES and COLUMNS.
shopt -s checkwinsize

# If set, the pattern "**" used in a pathname expansion context will
# match all files and zero or more directories and subdirectories.
#shopt -s globstar

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# set a fancy prompt (non-color, unless we know we "want" color)
case "$TERM" in
    xterm-color|*-256color) color_prompt=yes;;
esac

# uncomment for a colored prompt, if the terminal has the capability; turned
# off by default to not distract the user: the focus in a terminal window
# should be on the output of commands, not on the prompt
#force_color_prompt=yes

if [ -n "$force_color_prompt" ]; then
    if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
	# We have color support; assume it's compliant with Ecma-48
	# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
	# a case would tend to support setf rather than setaf.)
	color_prompt=yes
    else
	color_prompt=
    fi
fi

if [ "$color_prompt" = yes ]; then
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;32m\]\w\[\033[00m\]\$ '
else
    PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi
unset color_prompt force_color_prompt

# If this is an xterm set the title to user@host:dir
case "$TERM" in
xterm*|rxvt*)
    PS1="\[\e]0;${debian_chroot:+($debian_chroot)}\u@\h: \w\a\]$PS1"
    ;;
*)
    ;;
esac

function lgit() {
    git add --all
    git commit -am "$1"
    git push
}




# enable color support of ls and also add handy aliases
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
    #alias dir='dir --color=auto'
    #alias vdir='vdir --color=auto'

    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi

# colored GCC warnings and errors
#export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'

# some more ls aliases
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'

# Add an "alert" alias for long running commands.  Use like so:
#   sleep 10; alert
alias alert='notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e '\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\'')"'

# Alias definitions.
# You may want to put all your additions into a separate file like
# ~/.bash_aliases, instead of adding them here directly.
# See /usr/share/doc/bash-doc/examples in the bash-doc package.

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi
LS_COLORS=$LS_COLORS:'di=4;32:' ; export LS_COLORS
alias runcard='sudo /opt/netronome/bin/ovs-ctl start'
alias stopcard='sudo /opt/netronome/bin/ovs-ctl stop'
alias netronomeboot="sudo grub-reboot NetronomeBoot"


# Netronome SDK
PATH=$PATH:/opt/netronome/bin
export PATH


function lgit() {
    echo $(git add --all)
    echo $(git commit -am "$1")
    echo $(git push)
}

function serverstart(){
    echo $(sudo systemctl start nfp-sdk6-rte)
    echo $(sudo systemctl start nfp-hwdbg-srv)
    echo $(systemctl status nfp-sdk6-rte)
}

function serverstop(){
   echo $(sudo systemctl stop nfp-sdk6-rte)
   echo $( sudo systemctl stop nfp-hwdbg-srv)
   echo $(systemctl status nfp-sdk6-rte)
}

# INSTALLS #
alias agilio="apt-get install agilio-nfp-driver-dkms"

# KERNEL COMPILE #
alias installtools="sudo apt-get install git fakeroot build-essential ncurses-dev xz-utils libssl-dev bc flex libelf-dev bison"
alias ownconfig='cp -v /boot/config-$(uname -r) .config'
alias getsource='apt-get source linux-image-unsigned-$(uname -r)'
alias getsourcecustom='apt-get source linux-image-unsigned-4.15.0-72-generic'

# CONGESTION CONTROL #
alias ccchange='sudo emacs /etc/sysctl.conf'
alias loadcc='sudo sysctl -p'
alias ccversion='sysctl net.ipv4.tcp_available_congestion_control'
alias defer='echo 1 | sudo tee /sys/module/tcp_cubic_paced/parameters/tso_defer_size'
alias resetdefer='echo 0 | sudo tee /sys/module/tcp_cubic_paced/parameters/tso_defer_size'

# BASH && MISC #
alias bashrc='emacs ~/.bashrc &'
alias open="xdg-open"
alias searchword="grep -rnw . -e"
alias searchfile="grep -iRl"
alias reload="source /home/permki/.bashrc"
alias paced="cd /home/permki/Desktop/PacedLinux"
alias nic="cd /home/permki/Desktop/nic-firmware"
alias firm="cd /lib/firmware/netronome"

# BOOTS #
alias nboot="sudo grub-reboot Netronome_4.15 && sudo reboot now"
alias pboot="sudo grub-reboot Netronome_4.20 && sudo reboot now"
alias gboot="sudo grub-reboot Netronome_5.14 && sudo reboot now"

# PINGS AND DUMPS #
alias superping="sudo hping3 -i enp5s0np0 10.1.1.1 --fast"
alias psend="sudo tcpreplay -i enp5s0np0 /home/permki/Desktop/udp_v2.pcap"
alias shark="sudo tshark -x -i enp5s0np0"
alias dump="sudo tcpdump -i enp5s0np0 -s 0"
alias tcpsend="echo nisse | netcat 10.1.1.1 10000"
alias tcplisten="netcat -l -p 10000"

# NIC FIRMWARE MODS #

function compile(){
	firmpath="/lib/firmware/netronome"
	echo "sudo make nic/nic_AMDA0096-0001_2x10.nffw"
	sudo make nic/nic_AMDA0096-0001_2x10.nffw
	echo "sudo rm -f $firmpath/*.nffw"
	sudo rm -f $firmpath/*.nffw
	echo "sudo cp /home/permki/Desktop/nic-firmware/firmware/nic/flower/* $firmpath/flower"
	sudo cp /home/permki/Desktop/nic-firmware/firmware/nffw/nic/* $firmpath/flower
	for firmware in $(ls $firmpath/flower); do echo "sudo ln -sf $firmpath/flower/$firmware $firmpath/$firmware"; sudo ln -sf $firmpath/flower/$firmware $firmpath/$firmware; done
	echo "sudo modprobe -r nfp && sudo modprobe nfp"
	sudo modprobe -r nfp && sudo modprobe nfp
	ifupdown
}
function ifupdown(){
	echo "sudo ifdown enp5s0np0"
	sudo ifdown enp5s0np0
	echo "sudo ifup enp5s0np0"
	sudo ifup enp5s0np0
}

function limbo(){
	echo "sudo modprobe -r nfp && sudo modprobe nfp"
	sudo modprobe -r nfp && sudo modprobe nfp
	ifupdown
}
